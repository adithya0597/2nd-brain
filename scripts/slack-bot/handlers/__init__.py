"""Register all handlers with the Slack Bolt app."""
from slack_bolt import App


def register_all(app: App):
    """Register all event listeners, commands, and actions."""
    from . import capture, commands, actions, feedback

    capture.register(app)
    commands.register(app)
    actions.register(app)
    feedback.register(app)
