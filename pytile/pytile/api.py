"""Define an object to work directly with the API."""
import asyncio
import logging
from time import time
from typing import Dict, Optional
from uuid import uuid4

from aiohttp import ClientSession
from aiohttp.client_exceptions import ClientError

from .errors import InvalidAuthError, RequestError
from .tile import Tile

_LOGGER = logging.getLogger(__name__)

API_URL_SCAFFOLD = "https://production.tile-api.com/api/v1"

DEFAULT_API_VERSION = "1.0"
DEFAULT_APP_ID = "ios-tile-production"
DEFAULT_APP_VERSION = "2.89.1.4774"
DEFAULT_LOCALE = "en-US"
DEFAULT_TIMEOUT = 10
DEFAULT_USER_AGENT = "Tile/4774 CFNetwork/1312 Darwin/21.0.0"


class API:  # pylint: disable=too-many-instance-attributes
    """Define the API management object."""

    def __init__(
        self,
        email: str,
        password: str,
        session: ClientSession,
        *,
        client_uuid: Optional[str] = None,
        locale: str = DEFAULT_LOCALE,
    ) -> None:
        """Initialize."""
        self._client_established: bool = False
        self._email: str = email
        self._locale: str = locale
        self._password: str = password
        self._session: ClientSession = session
        self._session_expiry: Optional[int] = None
        self.client_uuid: str = str(uuid4()) if not client_uuid else client_uuid
        self.user_uuid: Optional[str] = None

    async def _async_request(self, method: str, endpoint: str, **kwargs) -> dict:
        """Make a request against Tile."""
        if self._session_expiry and self._session_expiry <= int(time() * 1000):
            await self.async_init()

        kwargs.setdefault("headers", {})
        kwargs["headers"]["User-Agent"] = DEFAULT_USER_AGENT
        kwargs["headers"]["tile_api_version"] = DEFAULT_API_VERSION
        kwargs["headers"]["tile_app_id"] = DEFAULT_APP_ID
        kwargs["headers"]["tile_app_version"] = DEFAULT_APP_VERSION
        kwargs["headers"]["tile_client_uuid"] = self.client_uuid

        async with self._session.request(
            method, f"{API_URL_SCAFFOLD}/{endpoint}", **kwargs
        ) as resp:
            print(resp.cookies)
            try:
                resp.raise_for_status()
                data = await resp.json()
            except ClientError as err:
                if "401" in str(err):
                    raise InvalidAuthError("Invalid credentials") from err
                raise RequestError(
                    f"Error requesting data from {endpoint}: {err}"
                ) from err

        _LOGGER.debug("Data received from /%s: %s", endpoint, data)

        return data

    async def async_get_tiles(self) -> Dict[str, Tile]:
        """Get all active Tiles from the user's account."""
        states = await self._async_request("get", "tiles/tile_states")

        details_tasks = {
            tile_uuid: self._async_request("get", f"tiles/{tile_uuid}")
            for tile_uuid in [tile["tile_id"] for tile in states["result"]]
        }

        results = await asyncio.gather(*details_tasks.values())

        return {
            tile_uuid: Tile(self._async_request, tile_data)
            for tile_uuid, tile_data, in zip(details_tasks, results)
        }

    async def async_init(self) -> None:
        """Create a Tile session."""
        # Invalidate the existing session expiry datetime (if it exists) so that the
        # next few requests don't fail:
        self._session_expiry = None

        if not self._client_established:
            await self._async_request(
                "put",
                f"clients/{self.client_uuid}",
                data={
                    "app_id": DEFAULT_APP_ID,
                    "app_version": DEFAULT_APP_VERSION,
                    "locale": self._locale,
                },
            )
            self._client_established = True

        resp = await self._async_request(
            "post",
            f"clients/{self.client_uuid}/sessions",
            data={"email": self._email, "password": self._password},
        )

        if not self.user_uuid:
            self.user_uuid = resp["result"]["user"]["user_uuid"]
        self._session_expiry = resp["result"]["session_expiration_timestamp"]


async def async_login(
    email: str,
    password: str,
    session: ClientSession,
    *,
    client_uuid: Optional[str] = None,
    locale: str = DEFAULT_LOCALE,
) -> API:
    """Return an authenticated client."""
    api = API(email, password, session, client_uuid=client_uuid, locale=locale)
    await api.async_init()
    return api
