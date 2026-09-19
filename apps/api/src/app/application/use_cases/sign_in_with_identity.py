import re
import uuid

from app.application.clock import Clock, utc_now
from app.application.errors import (
    EmailAlreadyRegisteredError,
    EmailNotVerifiedError,
    IdentityAlreadyLinkedError,
    IdentityCodeRejectedError,
    SsoSignInRefusedError,
    UserNotActiveError,
)
from app.application.ports.identity_provider import VerifiedIdentity
from app.application.ports.user_identity_repository import UserIdentityRepository
from app.application.ports.user_repository import UserRepository
from app.domain.user import CONTROL_CHARACTERS, InvalidEmailError, User, normalise_email

MAX_FULL_NAME_LENGTH = 200
_CONTROL_CHARACTERS = re.compile(f"[{CONTROL_CHARACTERS}]")


class SignInWithIdentity:
    """Finds or creates the user an identity provider vouches for.

    In this order:

    1. an unverified email is refused, whoever it is: the address proves nothing;
    2. the user already linked to ``(provider, subject)`` signs in, whatever email the
       provider reports today;
    3. otherwise the user who has that VERIFIED email is linked and signs in, keeping their
       password, unless they are already linked to a different subject of this provider
       (the mailbox changed hands at the provider: not the same person);
    4. otherwise a user is created, with no password, and linked.

    An inactive user never signs in. The lookups give the usual answer cheaply; the
    repositories' uniqueness rules are what make concurrent first sign-ins safe, and a lost
    race ends as the same user the winner created.
    """

    def __init__(
        self,
        users: UserRepository,
        identities: UserIdentityRepository,
        *,
        clock: Clock = utc_now,
    ) -> None:
        self._users = users
        self._identities = identities
        self._clock = clock

    async def execute(self, identity: VerifiedIdentity) -> User:
        if not identity.email_verified:
            raise EmailNotVerifiedError
        try:
            email = normalise_email(identity.email)
        except InvalidEmailError:
            raise IdentityCodeRejectedError from None

        user_id = await self._identities.find_user_id(identity.provider, identity.subject)
        if user_id is not None:
            return _active(await self._users.get_by_id(user_id))

        user = await self._users.get_by_email(email)
        if user is None:
            user = await self._create(email, identity.full_name)
        return await self._link(_active(user), identity)

    async def _create(self, email: str, full_name: str | None) -> User:
        user = User(
            id=uuid.uuid4(),
            email=email,
            full_name=_storable_name(full_name, email),
            hashed_password=None,
            is_active=True,
            created_at=self._clock(),
        )
        try:
            await self._users.add(user)
        except EmailAlreadyRegisteredError:
            # A concurrent sign-in or registration created that user first: join them.
            winner = await self._users.get_by_email(email)
            if winner is None:
                raise
            return winner
        return user

    async def _link(self, user: User, identity: VerifiedIdentity) -> User:
        try:
            await self._identities.link(
                user.id, identity.provider, identity.subject, linked_at=self._clock()
            )
        except IdentityAlreadyLinkedError:
            # Either a concurrent sign-in of this same identity linked it first (fine, as
            # long as it is to this user), or the user belongs to another subject.
            owner = await self._identities.find_user_id(identity.provider, identity.subject)
            if owner != user.id:
                raise SsoSignInRefusedError from None
        return user


def _active(user: User | None) -> User:
    if user is None or not user.is_active:
        raise UserNotActiveError
    return user


def _storable_name(full_name: str | None, email: str) -> str:
    """The provider's display name without control characters, cut to the column; the
    mailbox name when the provider gives none."""
    name = _CONTROL_CHARACTERS.sub("", full_name or "").strip()[:MAX_FULL_NAME_LENGTH].strip()
    return name or email.partition("@")[0][:MAX_FULL_NAME_LENGTH]
