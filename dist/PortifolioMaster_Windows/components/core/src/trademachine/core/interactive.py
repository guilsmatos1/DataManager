import os
from collections.abc import Callable


def interactive_history_path(app_name: str) -> str:
    """Returns the persistent history path for an interactive shell."""
    normalized = app_name.strip().lower().replace(" ", "_")
    return os.path.join(os.path.expanduser("~"), f".{normalized}_history")


def create_prompt_session(
    history_file: str,
    logger=None,
):
    """Builds a prompt_toolkit session when available."""
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
        from prompt_toolkit.history import FileHistory

        return PromptSession(
            history=FileHistory(history_file),
            auto_suggest=AutoSuggestFromHistory(),
        )
    except Exception as e:
        if logger is not None:
            logger.debug(
                "prompt_toolkit unavailable, falling back to plain input: %s",
                e,
            )
        return None


def read_interactive_input(
    prompt_session,
    prompt_text: str,
    fallback_reader: Callable[[str], str] | None = None,
) -> str:
    """Reads one interactive command using prompt history when available."""
    if prompt_session is None:
        if fallback_reader is None:
            fallback_reader = input
        return fallback_reader(prompt_text)

    from prompt_toolkit.formatted_text import ANSI

    return prompt_session.prompt(ANSI(prompt_text))
