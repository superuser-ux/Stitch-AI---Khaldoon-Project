# CANON-015 — 28-Day Calendar Model

## Rules
- Posts per day: 2.
- Post times: 9:00 AM UAE and 8:00 PM UAE.
- Total posts per 28-day round: 56.
- Dialect: Palestinian Arabic throughout.

## Pillar Distribution Across 28 Days
| Pillar | Posts |
|---|---:|
| P1 — Self | 22 |
| P2 — Relationships | 17 |
| P3 — Parenting | 9 |
| P4 — Work | 4 |
| P5 Meaning / العلاقة مع الله | 4 |
| Total | 56 |

## Weekly Format Distribution — Locked
| Format | Weekly Count |
|---|---:|
| Reel — Studio | 4 |
| Reel — Event Cut | 1 |
| Reel — iPhone | 2 |
| Reel — Podcast | 2 |
| Carousel | 3 |
| Pic + Caption | 1 |
| 3sec Reel + Caption | 1 |
| Total | 14 |

## HCS Assignment Rule
- Assign every post one HCS from the assigned pillar.
- Go through HCS in order from top to bottom within each pillar.
- When a round ends, the next round continues from where the previous round left off.
- When all 42 HCS have been covered, cycle begins again from 1.1 with different lenses.
- The lens used in round 1 must not be repeated in round 2 for the same HCS.

## Replication Rule
Keep the exact structure, pillar distribution, and weekly format distribution. Change only HCS assignment, lens, topic angle, hook, and script.

## Calendar Slot Schema
```json
{
  "slot_id": "R1-D01-AM",
  "round": 1,
  "day": 1,
  "time_uae": "09:00",
  "pillar_code": "P1_SELF",
  "format": "Reel — Studio",
  "hcs_id": "",
  "lens": "",
  "calendar_slot_status": "EMPTY"
}
```

## Calendar Slot Status Enum

- `EMPTY`
- `RESERVED`
- `DRAFT_ASSIGNED`
- `APPROVED_ASSIGNED`
- `SCHEDULED`
- `PUBLISHED`
- `SKIPPED`
- `REPLACED`
