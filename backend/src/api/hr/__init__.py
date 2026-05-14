"""kb-hr module (#150, PZ §7).

Foundation: employee directory + CRUD endpoints. HR_RESTRICTED tier.
Frontend pages, 1С:ZUP integration, КЭДО, attestation tracking,
column-level PII encryption — Stage 2+.
"""

from src.api.hr.models import HrEmployee
from src.api.hr.repository import HrEmployeeRepository, get_hr_employee_repository
from src.api.hr.router import router as hr_router

__all__ = [
    "HrEmployee",
    "HrEmployeeRepository",
    "get_hr_employee_repository",
    "hr_router",
]
