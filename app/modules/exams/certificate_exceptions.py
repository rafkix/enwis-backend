from fastapi import HTTPException, status


class CertificateNotFound(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_404_NOT_FOUND, "Certificate not found")


class CertificateNotEligible(HTTPException):
    def __init__(self, detail: str = "This attempt is not eligible for a certificate") -> None:
        super().__init__(status.HTTP_400_BAD_REQUEST, detail)


class CertificatesDisabled(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_400_BAD_REQUEST,
            "Certificates are not enabled for this test",
        )


class NotCertificateOwner(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_403_FORBIDDEN, "You do not own this certificate")
