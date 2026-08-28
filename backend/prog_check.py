from datetime import date
from decimal import Decimal
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.db.models import CostRate
from app.services import configuracion

eng = create_engine("postgresql+psycopg://factuchat:dev-admin-pass@postgres:5432/factuchat")
with Session(eng) as db:
    configuracion.programar_tarifa(db, "INFRA", "Emision de comprobante", Decimal("0.005"), "comprobante", date(2026,12,1))
    configuracion.programar_tarifa(db, "INFRA", "Emision de comprobante", Decimal("0.007"), "comprobante", date(2026,12,1))
    filas = db.scalars(select(CostRate).where(CostRate.proveedor=="INFRA", CostRate.vigente_desde==date(2026,12,1))).all()
    print("filas creadas con vigente_desde=2026-12-01:", len(filas))
    for f in filas:
        print("  costo", f.costo_unitario, "concepto", f.concepto, "vigente_hasta", f.vigente_hasta)
    db.rollback()
