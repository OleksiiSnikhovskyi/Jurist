from sqlalchemy.orm import Session

from app.models.official_source_search_run import OfficialSourceSearchRun
from app.schemas.n8n_schema import (
    N8nOfficialSourceSearchPlanRequest,
    N8nOfficialSourceSearchPlanResponse,
    OfficialSourceSearchUrlDecision,
)
from app.services.access_control import AccessControlService, WorkspacePermission
from scripts.legal_source_policy import (
    OFFICIAL_DOMAINS,
    has_blocked_source_hint,
    is_official_source_url,
    normalize_domain,
)

ALLOWED_SEARCH_TRIGGERS = frozenset(
    {
        "low_rag_confidence",
        "current_validity_required",
        "exact_reference_verification",
    }
)
LOW_CONFIDENCE_THRESHOLD = 0.45
MAX_SITE_QUERIES = 12


class OfficialSourceSearchPlanner:
    def __init__(
        self,
        db: Session,
        access_control: AccessControlService | None = None,
    ) -> None:
        self.db = db
        self.access_control = access_control or AccessControlService(db)

    def build_plan(
        self,
        request: N8nOfficialSourceSearchPlanRequest,
    ) -> N8nOfficialSourceSearchPlanResponse:
        self.access_control.require_permission(
            workspace_id=request.workspace_id,
            user_id=request.user_id,
            permission=WorkspacePermission.READ,
        )
        allowed_by_trigger = self._allowed_by_trigger(request)
        accepted, rejected = self._classify_candidate_urls(request.candidate_urls)
        domains = sorted(OFFICIAL_DOMAINS)
        site_queries = self._site_queries(request, domains) if allowed_by_trigger else []
        run = OfficialSourceSearchRun(
            workspace_id=request.workspace_id,
            user_id=request.user_id,
            trigger_reason=request.trigger_reason,
            query=request.query,
            search_allowed=allowed_by_trigger,
            allowed_domains=domains,
            site_queries=site_queries,
            accepted_urls=[item.model_dump() for item in accepted],
            rejected_urls=[item.model_dump() for item in rejected],
            metadata_json={
                "rag_confidence": request.rag_confidence,
                "requires_current_validity": request.requires_current_validity,
                "exact_references": request.exact_references,
            },
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return N8nOfficialSourceSearchPlanResponse(
            ok=True,
            search_allowed=allowed_by_trigger,
            search_run_id=run.id,
            trigger_reason=request.trigger_reason,
            allowed_domains=domains,
            site_queries=site_queries,
            accepted_urls=accepted,
            rejected_urls=rejected,
            message=(
                "Official-source search plan prepared."
                if allowed_by_trigger
                else "Official-source search was not triggered by the supplied conditions."
            ),
        )

    def _allowed_by_trigger(self, request: N8nOfficialSourceSearchPlanRequest) -> bool:
        if request.trigger_reason in ALLOWED_SEARCH_TRIGGERS:
            return True
        if request.rag_confidence is not None and request.rag_confidence < LOW_CONFIDENCE_THRESHOLD:
            return True
        if request.requires_current_validity:
            return True
        return bool(request.exact_references)

    def _classify_candidate_urls(
        self,
        urls: list[str],
    ) -> tuple[list[OfficialSourceSearchUrlDecision], list[OfficialSourceSearchUrlDecision]]:
        accepted: list[OfficialSourceSearchUrlDecision] = []
        rejected: list[OfficialSourceSearchUrlDecision] = []
        for url in urls:
            domain = normalize_domain(url)
            if has_blocked_source_hint(url):
                rejected.append(
                    OfficialSourceSearchUrlDecision(
                        url=url,
                        domain=domain,
                        reason="blocked_source_hint",
                    )
                )
            elif is_official_source_url(url):
                accepted.append(
                    OfficialSourceSearchUrlDecision(
                        url=url,
                        domain=domain,
                        reason="official_domain_allowed",
                    )
                )
            else:
                rejected.append(
                    OfficialSourceSearchUrlDecision(
                        url=url,
                        domain=domain,
                        reason="domain_not_allowlisted",
                    )
                )
        return accepted, rejected

    def _site_queries(
        self,
        request: N8nOfficialSourceSearchPlanRequest,
        domains: list[str],
    ) -> list[str]:
        terms = [request.query.strip()]
        terms.extend(ref.strip() for ref in request.exact_references if ref.strip())
        unique_terms = []
        for term in terms:
            if term and term not in unique_terms:
                unique_terms.append(term)
        queries: list[str] = []
        for term in unique_terms:
            for domain in domains:
                queries.append(f"site:{domain} {term}")
                if len(queries) >= MAX_SITE_QUERIES:
                    return queries
        return queries
