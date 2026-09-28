"""Fill an EMPTY development database with fictional test data.

Usage: python -m ess.tools.seed_test_data [--members 400] [--seed 42]

Needs ESS_DATABASE_URL, ESS_PII_KEYS and ESS_BLIND_INDEX_KEY. Refuses to run when
ESS_ENVIRONMENT=prod or when the database already contains members. All people, e-mails
(@example.org), addresses and phone numbers are made up.
"""

import argparse
import random
import sys
import uuid
from datetime import date, timedelta

from sqlalchemy import func, select

from ess.config import get_settings
from ess.db import get_sessionmaker
from ess.models import CertificateType, Club, Document, Member, MemberCertificate, Membership, MembershipStatus as S
from ess.services import members, memberships, positions
from ess.services.access import SYSTEM
from ess.services.members import MemberData

MALE_FIRST = ["Ján", "Peter", "Martin", "Michal", "Tomáš", "Jozef", "Marek", "Juraj", "Pavol", "Ľubomír",
              "Štefan", "Ondrej", "Branislav", "Dušan", "Igor", "Radoslav", "Matej", "Samuel", "Filip", "Vladimír"]
FEMALE_FIRST = ["Mária", "Jana", "Katarína", "Zuzana", "Eva", "Lucia", "Andrea", "Monika", "Veronika",
                "Ľubica", "Barbora", "Simona", "Petra", "Alžbeta", "Hana"]
MALE_LAST = ["Novák", "Horváth", "Kováč", "Varga", "Tóth", "Nagy", "Baláž", "Szabó", "Molnár", "Lukáč",
             "Kráľ", "Hudák", "Polák", "Šimko", "Gregor", "Mikuš", "Blaho", "Kučera", "Ondrejka", "Hric"]
FEMALE_LAST = ["Nováková", "Horváthová", "Kováčová", "Vargová", "Tóthová", "Balážová", "Lukáčová",
               "Kráľová", "Hudáková", "Poláková", "Šimková", "Gregorová", "Mikušová", "Blahová", "Hricová"]
PLACES = ["Demänová", "Plavecký kras", "Muránska planina", "Slovenský raj", "Strážovské vrchy", "Horehronie",
          "Liptov", "Orava", "Malé Karpaty", "Veľká Fatra", "Slovenský kras", "Súľov", "Tribeč", "Považie",
          "Zemplín", "Spiš", "Gemer", "Tatry", "Čierny Hron", "Harmanec"]
TOWNS = ["Bratislava", "Košice", "Žilina", "Banská Bystrica", "Liptovský Mikuláš", "Rožňava", "Poprad",
         "Martin", "Trenčín", "Brezno", "Ružomberok", "Prešov", "Nitra", "Trnava"]
STREETS = ["Hlavná", "Školská", "Záhradná", "Lipová", "Jaskyniarska", "Horská", "Krátka", "Nová"]
TITLES_BEFORE = ["Ing.", "Mgr.", "RNDr.", "Bc.", "MUDr."]
TITLES_AFTER = ["PhD.", "CSc."]


def _person(rng: random.Random, index: int) -> MemberData:
    female = rng.random() < 0.3
    first = rng.choice(FEMALE_FIRST if female else MALE_FIRST)
    last = rng.choice(FEMALE_LAST if female else MALE_LAST)
    birth = date(1945, 1, 1) + timedelta(days=rng.randrange(0, 63 * 365))
    return MemberData(
        first_name=first,
        last_name=last,
        title_before=rng.choice(TITLES_BEFORE) if rng.random() < 0.2 else None,
        title_after=rng.choice(TITLES_AFTER) if rng.random() < 0.05 else None,
        birth_date=birth if rng.random() < 0.8 else None,
        email=f"clen{index:04d}@example.org" if rng.random() < 0.85 else None,
        address=f"{rng.choice(STREETS)} {rng.randint(1, 120)}, {rng.choice(TOWNS)}" if rng.random() < 0.7 else None,
        phone=f"+421 9{rng.randint(0, 99):02d} {rng.randint(100, 999)} {rng.randint(100, 999)}"
        if rng.random() < 0.6 else None,
        card_number=str(1000 + index) if rng.random() < 0.5 else None,
        member_since=date(rng.randint(min(max(1970, birth.year + 15), 2025), 2025), rng.randint(1, 12), 1),
    )


def seed(member_count: int, rng_seed: int) -> None:
    settings = get_settings()
    if settings.environment == "prod":
        sys.exit("Refusing to seed test data in production (ESS_ENVIRONMENT=prod).")
    with get_sessionmaker()() as session:
        if session.scalar(select(func.count()).select_from(Member)):
            sys.exit("The database already contains members - test data are only for an empty database.")
        _seed(session, random.Random(rng_seed), member_count)


def _seed(session, rng: random.Random, member_count: int) -> None:

    start = date(2026, 1, 1)
    clubs = []
    for index, place in enumerate(PLACES, start=1):
        club = Club(id=uuid.uuid4(), name=f"Jaskyniarska skupina {place}", short_name=f"JS {place}", code=f"JS{index:02d}",
                    is_unaffiliated=False, uses_candidates=rng.random() < 0.7, active=True)
        session.add(club)
        clubs.append(club)
    unaffiliated = session.scalars(select(Club).where(Club.is_unaffiliated)).one()
    session.flush()

    created: list[tuple[Member, Club]] = []
    for i in range(1, member_count + 1):
        if i % 50 == 0:
            session.flush()
            print(f"  {i}/{member_count} members")
        member = members.create_member(session, SYSTEM, _person(rng, i))
        club = unaffiliated if rng.random() < 0.05 else rng.choice(clubs)
        roll = rng.random()
        if club.uses_candidates and roll < 0.08:
            status = S.CANDIDATE
        elif roll < 0.12:
            status = S.PENDING_ACTIVATION
        else:
            status = S.MEMBER
        membership = memberships.add_membership(session, SYSTEM, member.id, club.id, status,
                                                on=member.member_since or start)
        if status == S.MEMBER:
            if rng.random() < 0.05:
                memberships.change_status(session, SYSTEM, membership.id, S.SUSPENDED, on=start)
                continue
            created.append((member, club))
            if rng.random() < 0.1 and club is not unaffiliated:
                second = rng.choice([c for c in clubs if c is not club])
                memberships.add_membership(session, SYSTEM, member.id, second.id, S.MEMBER, on=start)

    active_by_club: dict[uuid.UUID, list[Member]] = {}
    for member, club in created:
        active_by_club.setdefault(club.id, []).append(member)
    chairs = set()
    for club in clubs:
        candidates = [m for m in active_by_club.get(club.id, []) if m.id not in chairs]
        if candidates:
            chair = rng.choice(candidates)
            positions.assign_position(session, SYSTEM, "club_chair", chair.id, club.id, valid_from=start)
            chairs.add(chair.id)
    pool = [m for m, c in created if m.id not in chairs and c is not unaffiliated]
    rng.shuffle(pool)
    holders = set(chairs)
    for code in ["sss_chair", "sss_vice_chair", "audit_chair"] + ["board_member"] * 5 + ["audit_member"] * 2:
        holder = pool.pop()
        positions.assign_position(session, SYSTEM, code, holder.id, valid_from=start)
        holders.add(holder.id)

    cert_types = session.scalars(select(CertificateType)).all()
    for member, _ in rng.sample(created, k=min(len(created), member_count // 5)):
        session.add(MemberCertificate(id=uuid.uuid4(), member_id=member.id,
                                      certificate_type_id=rng.choice(cert_types).id,
                                      valid_from=date(rng.randint(2015, 2025), 1, 1)))

    expelled = rng.sample([m for m, _ in created if m.id not in holders], k=2)
    for member in expelled:
        members.expel_member(session, SYSTEM, member.id, "Testovacie vylúčenie (fiktívne uznesenie VZ)", on=start)

    # A few chairs propose promoting candidates; a few members leave their only club.
    for membership in session.scalars(
        select(Membership).where(Membership.valid_to.is_(None), Membership.status == S.CANDIDATE)
    ).all()[:4]:
        memberships.change_status(session, SYSTEM, membership.id, S.PENDING_ACTIVATION, on=start)
    leavers = [m for m, _ in created if m.id not in holders and m not in expelled]
    for member in rng.sample(leavers, k=min(3, len(leavers))):
        open_ms = memberships.open_memberships(session, member.id)
        if len(open_ms) == 1:
            memberships.terminate(session, SYSTEM, open_ms[0].id, on=start)

    members.apply_age_reduced_fee(session, SYSTEM, fee_year=2026, age=62)

    for title, days in (("Stanovy SSS (test)", None), ("Výnimka ŠOP – testovací dokument", 365),
                        ("Etický kódex jaskyniara (test)", None)):
        session.add(Document(id=uuid.uuid4(), title=title, url="https://example.org/dokument.pdf",
                             valid_until=start + timedelta(days=days) if days else None))

    session.commit()
    print(f"Done: {len(clubs)} clubs, {member_count} members, {len(chairs)} club chairs.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--members", type=int, default=400)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    seed(args.members, args.seed)


if __name__ == "__main__":
    main()
