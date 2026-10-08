import uuid

from fastapi import APIRouter, Depends

from app.modules.auth.dependencies import get_active_user
from app.modules.auth.models import User
from app.modules.exams.certificate_dependencies import get_certificate_service
from app.modules.exams.certificate_schemas import (
    CertificateListResponse,
    CertificateResponse,
)
from app.modules.exams.certificate_service import CertificateService

router = APIRouter(tags=["Certificates"])


@router.get(
    "/attempts/{attempt_id}/certificate",
    response_model=CertificateResponse,
)
async def get_or_issue_certificate(
    attempt_id: uuid.UUID,
    current_user: User = Depends(get_active_user),
    service: CertificateService = Depends(get_certificate_service),
):
    """Fetch the certificate for one of the caller's own completed attempts,
    issuing it on first request if the attempt passed and the test allows it.
    """
    return await service.issue_manually(attempt_id, current_user.id)


@router.get("/certificates/me", response_model=CertificateListResponse)
async def list_my_certificates(
    current_user: User = Depends(get_active_user),
    service: CertificateService = Depends(get_certificate_service),
):
    items = await service.list_my_certificates(current_user.id)
    return CertificateListResponse(items=items, total=len(items))


@router.get("/certificates/{certificate_id}", response_model=CertificateResponse)
async def get_certificate(
    certificate_id: uuid.UUID,
    current_user: User = Depends(get_active_user),
    service: CertificateService = Depends(get_certificate_service),
):
    return await service.get_by_id_for_user(certificate_id, current_user.id)


@router.get(
    "/certificates/verify/{serial_number}",
    response_model=CertificateResponse,
)
async def verify_certificate(
    serial_number: str,
    service: CertificateService = Depends(get_certificate_service),
):
    """Public endpoint — no authentication required. Lets anyone (e.g. an
    employer) verify a certificate's authenticity from its serial number.
    """
    return await service.verify_by_serial(serial_number)
