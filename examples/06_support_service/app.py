"""Level 6: a multi-file support service with legacy capabilities."""

from support_models import SupportRequest, SupportResponse
from support_operations import create_ticket, load_customer, load_policy

from summonpot import Required, Summon, UsageLimits
from summonpot.runtime import Runtime

runtime = Runtime(
    retries=3,
    usage_limits=UsageLimits(request_limit=10, total_tokens_limit=12_000),
    timeout=60.0,
)
summon = Summon("support-service", runtime=runtime)


@summon("/support")
def handle_support(
    request: SupportRequest,
    customer=Required(load_customer),
    policy=Required(load_policy),
    ticket=Required(create_ticket),
) -> SupportResponse:
    """Handle the customer's support message. Load the customer. Select the relevant approved policy. Mark confirmed outages urgent and everything else normal. Create one ticket, then write a brief reply grounded in the customer record and policy."""
    ...


if __name__ == "__main__":
    summon.serve(host="127.0.0.1", port=8000)
