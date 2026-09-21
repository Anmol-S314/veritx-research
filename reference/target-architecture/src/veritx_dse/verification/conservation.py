from veritx_dse.workload.messages import validate_message_conservation
from veritx_dse.workload.traffic import validate_traffic_conservation


def verify_workload_to_traffic(graph,messages,traffic):
    validate_message_conservation(graph,messages)
    validate_traffic_conservation(messages,traffic)
