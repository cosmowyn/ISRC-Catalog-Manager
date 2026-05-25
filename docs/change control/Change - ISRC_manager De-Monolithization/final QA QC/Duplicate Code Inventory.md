# Duplicate Code Inventory

| Finding | Files | Symbols reviewed | Rationale | Final status | Active remediation |
| --- | --- | --- | --- | --- | --- |
| Watermark helpers (`authenticity` vs `forensics`) | `isrc_manager/authenticity/watermark.py`, `isrc_manager/forensics/watermark.py` | `pack_token`, `unpack_token`, `sync_and_payload_bits` | Different domain formats, byte sizes, sync words, and return models; intentional protocol boundary by workflow semantics. | `confirmed intentional` | Removed from active duplicate-remediation scope |
| Track service/protocol names (`TrackService`, `TrackMediaSourceHandle`) | `isrc_manager/media/waveform_cache.py`, `isrc_manager/services/tracks.py` | `TrackService`, `TrackMediaSourceHandle` | Protocol contracts and concrete implementations serve different abstraction layers and call sites. | `confirmed intentional` | Removed from active duplicate-remediation scope |

No additional duplicate-remediation actions are required for these findings.
