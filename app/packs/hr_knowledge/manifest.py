from app.platform.packs.knowledge import KnowledgeComponentContribution as C
from app.platform.packs.knowledge import KnowledgePackContribution


def build_knowledge_contribution() -> KnowledgePackContribution:
    prefix = "app.packs.hr_knowledge.contributions"
    return KnowledgePackContribution(
        projectors=(C("hr.projector.ontology", "1.0.0", f"{prefix}:project"),),
        requirement_compilers=(C("hr.requirement.temporal", "1.0.0", f"{prefix}:compile_requirements"),),
        entity_alias_providers=(C("hr.alias.lexicon", "1.0.0", f"{prefix}:aliases"),),
        applicability_providers=(C("hr.applicability.employment", "1.0.0", f"{prefix}:applicability"),),
        resolver_providers=(C("hr.resolver.document_family", "1.0.0", f"{prefix}:resolve"),),
        answer_renderers=(C("hr.renderer.vocabulary", "1.0.0", f"{prefix}:render_vocabulary"),),
        invariant_contributions=(C("hr.invariant.temporal", "1.0.0", f"{prefix}:invariants"),),
    )
