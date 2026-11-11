"""Records of a task (service/db/work_records.py): photos and PDF reports in file storage by type
and size, who deletes them, comments and payments with their rules."""

from __future__ import annotations

from sqlalchemy import select

from floorplan_engine.service.db import work
from floorplan_engine.service.db import work_records as records
from floorplan_engine.service.db.models import AuditEvent
from floorplan_engine.service.objects import work_prefix
from tests.service.conftest import PNG, World, fails


def test_photos(world: World) -> None:
    plan, chases, _ = world.approved()
    with fails(415):
        records.add_photo(
            world.db,
            world.store,
            world.project,
            plan,
            chases,
            b"x",
            "a.txt",
            "text/plain",
            "",
            world.installer,
        )
    with fails(413):
        world.photo(chases, world.installer, b"0" * (records.PHOTO_MAX + 1))
    with fails(422, "пустой"):
        world.photo(chases, world.installer, b"")
    with fails(403):
        world.photo(chases, world.viewer)
    world.photo(chases, world.installer)
    world.photo(chases, world.code)  # the client too: a photo of a defect
    mine, theirs = chases.photos
    assert mine.object_key.startswith(work_prefix(world.project.id) + f"/{chases.id}/")
    assert mine.object_key.endswith(".png") and world.store.get(mine.object_key) == PNG
    assert (mine.size, mine.user_id, theirs.author_label) == (
        len(PNG),
        world.users["i"].id,
        "код: Иван",
    )
    with fails(403, "автор"):
        records.delete_photo(world.db, world.store, world.project, plan, mine, world.client)
    with fails(403):  # a code has no user: only the studio removes its photo
        records.delete_photo(world.db, world.store, world.project, plan, theirs, world.code)
    key = mine.object_key
    records.delete_photo(world.db, world.store, world.project, plan, mine, world.installer)
    assert not world.store.exists(key) and chases.photos == [theirs]
    records.delete_photo(world.db, world.store, world.project, plan, theirs, world.owner)
    assert chases.photos == []


def test_comments_and_payments(world: World) -> None:
    plan, chases, _ = world.approved()
    with fails(403):
        records.add_comment(plan, chases, "привет", world.viewer)
    with fails(422, "text"):
        records.add_comment(plan, chases, "  ", world.installer)
    records.add_comment(plan, chases, " готово к приёмке ", world.installer)
    assert [(c.kind, c.text, c.author_label) for c in chases.comments] == [
        ("comment", "готово к приёмке", "I")
    ]
    pay = {"amount": 500, "paid_on": "2026-11-10", "note": "аванс"}
    with fails(403):
        records.add_payment(world.db, world.project, plan, chases, pay, world.client)
    with fails(422, "amount"):
        records.add_payment(
            world.db, world.project, plan, chases, {**pay, "amount": 0}, world.owner
        )
    with fails(422, "paid_on"):
        records.add_payment(
            world.db, world.project, plan, chases, {**pay, "paid_on": "x"}, world.owner
        )
    payment = records.add_payment(world.db, world.project, plan, chases, pay, world.owner)
    assert work.totals(chases).paid == 500.0 and not work.totals(chases).settled
    with fails(403):
        records.delete_payment(world.db, world.project, plan, payment, world.installer)
    records.delete_payment(world.db, world.project, plan, payment, world.owner)
    assert work.totals(chases).paid == 0.0
    actions = world.db.scalars(select(AuditEvent.action)).all()
    assert {"work_payment", "work_payment_delete"} <= set(actions)
