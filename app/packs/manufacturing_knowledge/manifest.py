from app.platform.packs.knowledge import KnowledgeComponentContribution as C
from app.platform.packs.knowledge import KnowledgePackContribution


def build_knowledge_contribution() -> KnowledgePackContribution:
    prefix = "app.packs.manufacturing_knowledge.contributions"
    return KnowledgePackContribution(
        projectors=(C("manufacturing.projector.ontology", "1.0.0", f"{prefix}:project"),),
        requirement_compilers=(C("manufacturing.requirement.sop", "1.0.0", f"{prefix}:compile_requirements"),),
        entity_alias_providers=(C("manufacturing.alias.lexicon", "1.0.0", f"{prefix}:aliases"),),
        applicability_providers=(C("manufacturing.applicability.sop", "1.0.0", f"{prefix}:applicability"),),
        resolver_providers=(C("manufacturing.resolver.document_family", "1.0.0", f"{prefix}:resolve"),),
        answer_renderers=(C("manufacturing.renderer.vocabulary", "1.0.0", f"{prefix}:render_vocabulary"),),
        invariant_contributions=(C("manufacturing.invariant.safety", "1.0.0", f"{prefix}:invariants"),),
    )
