"""Run order of the Azure components (dependency order; same order as the AWS and GCP plans)."""


def plan():
    from .components import (c01_access, c02_channels, c03_runtime, c04_gateway, c05_approval, c06_knowledge, c07_tools,
                             c08_observability, c09_memory, c10_models, c11_response, c12_pipeline, c13_governance)
    return [(1, c01_access.sign_in), (2, c02_channels.run), (12, c12_pipeline.run), (6, c06_knowledge.run), (7, c07_tools.run),
            (1, c01_access.edge), (4, c04_gateway.run), (5, c05_approval.setup), (3, c03_runtime.run), (9, c09_memory.run),
            (5, c05_approval.run), (10, c10_models.run), (11, c11_response.run), (8, c08_observability.run), (13, c13_governance.run)]
