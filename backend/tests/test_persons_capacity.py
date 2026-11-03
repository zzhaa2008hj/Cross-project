from app.models import Person


def _person(db, name="李四", monthly=30.0):
    p = Person(name=name, monthly_capacity=monthly, edited_in_app=True)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def test_create_person_defaults_monthly_capacity_to_30(client):
    r = client.post("/api/persons", json={"name": "李四"})
    assert r.status_code == 201
    assert r.json()["monthly_capacity"] == 30.0


def test_create_person_accepts_monthly_capacity(client):
    r = client.post("/api/persons", json={"name": "李四", "monthly_capacity": 20.5})
    assert r.status_code == 201
    assert r.json()["monthly_capacity"] == 20.5


def test_patch_monthly_capacity(client, db):
    p = _person(db)
    r = client.patch(f"/api/persons/{p.id}", json={"monthly_capacity": 12})
    assert r.status_code == 200
    assert r.json()["monthly_capacity"] == 12.0


def test_patch_explicit_null_monthly_capacity_is_422(client, db):
    r = client.patch(f"/api/persons/{_person(db).id}", json={"monthly_capacity": None})
    assert r.status_code == 422


def test_patch_non_half_step_is_422(client, db):
    r = client.patch(f"/api/persons/{_person(db).id}", json={"monthly_capacity": 0.3})
    assert r.status_code == 422


def test_patch_without_field_leaves_value_untouched(client, db):
    r = client.patch(f"/api/persons/{_person(db).id}", json={"note": "只改备注"})
    assert r.status_code == 200
    assert r.json()["monthly_capacity"] == 30.0
