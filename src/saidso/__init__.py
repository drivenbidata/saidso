"""SaidSo — record, transcribe and organise meetings on your own machine.

The package is layered so each piece is usable on its own:

    capture/     getting audio off the machine (platform backends)
    transcribe/  audio -> timestamped segments (faster-whisper)
    parse/       any transcript format -> clean Speaker: text
    output/      segments -> a markdown transcript, routed to a project
    tracker/     the deterministic half of action tracking (sweep + index)
    sync/        optional, guarded git mirroring of the notes directory

Synthesis — turning a transcript into a meeting note — is deliberately not
here. saidso stops at a clean, well-named transcript in the inbox; an agent
you choose reads it using the prompts in agent-pack/ — see its README.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
