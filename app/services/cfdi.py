"""
CFDI 4.0 service — PAC integration for Mexican tax invoices.

Two implementations:
- `MockCfdi` — dev mode; generates synthetic PDF/XML
- `SolucionFactibleCfdi` — production; calls the SolucionFactible API

Usage:
    cfdi = get_cfdi_adapter()
    result = await cfdi.stamp(invoice_data)
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class CfdiStampResult:
    """Result from a PAC stamping request."""

    cfdi_uuid: str
    xml_url: str
    pdf_url: str
    stamped_at: datetime


@dataclass
class InvoiceData:
    """Data needed to stamp a CFDI 4.0 invoice."""

    rfc_emisor: str
    rfc_receptor: str
    cfdi_use: str = "G03"  # G03 = servicios profesionales
    payment_method: str = "PPD"  # PPD = pago diferido, PUE = pago único
    subtotal: Decimal = Decimal("0.00")
    iva: Decimal = Decimal("0.00")
    total: Decimal = Decimal("0.00")
    description: str = "Servicios de mudanza / flete"


class MockCfdi:
    """Dev-mode CFDI adapter. Generates synthetic UUIDs + placeholder files."""

    async def stamp(self, data: InvoiceData) -> CfdiStampResult:
        """Simulate a PAC stamping. Returns a deterministic result."""
        cfdi_uuid = str(uuid.uuid4())
        now = datetime.utcnow()
        # Create mock files in a temp-like location
        out_dir = Path("mobbit-backend-service_data") / "cfdi"
        out_dir.mkdir(parents=True, exist_ok=True)

        xml_path = out_dir / f"cfdi_{cfdi_uuid[:8]}.xml"
        pdf_path = out_dir / f"cfdi_{cfdi_uuid[:8]}.pdf"

        # Write minimal mock XML
        xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    Version="4.0"
    Serie="A"
    Folio="{cfdi_uuid[:8]}"
    Fecha="{now.isoformat()}"
    FormaPago="{data.payment_method}"
    MetodoPago="PPD"
    Moneda="MXN"
    Total="{data.total}">
    <cfdi:Emisor Rfc="{data.rfc_emisor}" Nombre="Mobbit Mexico S.A. de C.V." RegimenFiscal="601"/>
    <cfdi:Receptor Rfc="{data.rfc_receptor}" Nombre="Cliente" UsoCFDI="{data.cfdi_use}"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="78121700" Cantidad="1" ClaveUnidad="E48"
            Descripcion="{data.description}" ValorUnitario="{data.subtotal}" Importe="{data.subtotal}"
            ObjetoImp="02">
            <cfdi:Impuestos>
                <cfdi:Traslados>
                    <cfdi:Traslado Base="{data.subtotal}" Impuesto="002" TipoFactor="Tasa"
                        TasaOCuota="0.160000" Importe="{data.iva}"/>
                </cfdi:Traslados>
            </cfdi:Impuestos>
        </cfdi:Concepto>
    </cfdi:Conceptos>
    <cfdi:Impuestos TotalImpuestosTrasladados="{data.iva}">
        <cfdi:Traslados>
            <cfdi:Traslado Base="{data.subtotal}" Impuesto="002" TipoFactor="Tasa"
                TasaOCuota="0.160000" Importe="{data.iva}"/>
        </cfdi:Traslados>
    </cfdi:Impuestos>
    <cfdi:Complemento>
        <tfd:TimbreFiscalDigital xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
            UUID="{cfdi_uuid}" FechaTimbrado="{now.isoformat()}"
            RfcProvCertif="AAA010101AAA" SelloCFD="mock-sello-cfd"/>
    </cfdi:Complemento>
</cfdi:Comprobante>"""
        xml_path.write_text(xml_content)
        # Mock PDF (just a placeholder)
        pdf_path.write_text(f"CFDI PDF placeholder for UUID {cfdi_uuid}")

        log.info("MockCfdi stamped invoice: uuid=%s", cfdi_uuid)
        return CfdiStampResult(
            cfdi_uuid=cfdi_uuid,
            xml_url=str(xml_path),
            pdf_url=str(pdf_path),
            stamped_at=now,
        )

    async def cancel(self, cfdi_uuid: str, reason: str = "02") -> bool:
        """Simulate a PAC cancellation."""
        log.info("MockCfdi cancelled invoice: uuid=%s reason=%s", cfdi_uuid, reason)
        return True


def get_cfdi_adapter() -> MockCfdi:
    """Return the appropriate CFDI adapter based on environment."""
    # For now, always return MockCfdi. Production would check
    # settings and return SolucionFactibleCfdi when configured.
    return MockCfdi()
