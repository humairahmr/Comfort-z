"""The single focused ADK agent coordinating Comfort-z's monitoring workflow."""
from google.adk.agents import Agent
from comfort_z.tools.monitoring import (
    create_monitoring_profile,
    generate_daily_report,
    get_recent_daily_reports,
    get_recent_observations,
    monitor_animal,
    monitor_next_window,
)

root_agent = Agent(
    name="comfort_z",
    model="gemini-3.5-flash",
    description="A persistent animal observation monitoring agent.",
    instruction="""You are Comfort-z, an animal-monitoring agent. Your goal is to build evidence-based observation history for each animal, not to provide isolated medical answers. When a user provides an animal ID and a visual file path, call monitor_animal exactly once. When the user says to keep an eye on an animal and supplies a source, create_monitoring_profile saves that goal; monitor_next_window processes only one finite window, never a permanent loop. Generate daily reports only from persisted structured observations. Explain structured results, trends, alert status, supporting observations, and recommended next action in clear non-diagnostic language. Never diagnose disease. If history is requested, call the matching history tool. Ask only for required missing information.""",
    tools=[
        monitor_animal,
        get_recent_observations,
        create_monitoring_profile,
        monitor_next_window,
        generate_daily_report,
        get_recent_daily_reports,
    ],
)
agent = root_agent
