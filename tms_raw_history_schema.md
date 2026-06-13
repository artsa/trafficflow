# TMS Raw History CSV Schema

Source: <https://tie.digitraffic.fi/swagger/#/TMS%20V1/tmsRawHistory>
OpenAPI spec: <https://tie.digitraffic.fi/swagger/openapi.json>
Schema ref: `#/components/schemas/TmsRawHistoryCsv`

## File Naming

```
lamraw_{tmsNumber}_{yearShort}_{dayNumber}.csv
```

- `tmsNumber` — TMS station `tmsNumber` field (NOT the station `id`)
- `yearShort` — last two digits of the year (e.g. 25 → 2025)
- `dayNumber` — ordinal day of year (1–366, accounting for leap years)

**Example:** `lamraw_109_25_164.csv` = station 109, 2025, June 13

## Endpoint

```
GET https://tie.digitraffic.fi/api/tms/v1/history/raw/lamraw_{tmsNumber}_{yearShort}_{dayNumber}.csv
```

Recommended headers:

```
User-Agent: YourApp/1.0
Digitraffic-User: YourApp/1.0
```

## Column Definitions

Delimiter: **semicolon (`;`)**
Header row: **none** — columns are positional.

| # | Field name         | Type    | Range       | Description |
|---|--------------------|---------|-------------|-------------|
| 1 | `tmsNumber`        | int32   | —           | TMS station tmsNumber (matches filename, NOT station id) |
| 2 | `yearShort`        | int32   | 0–99        | Year, last two digits |
| 3 | `dayNumber`        | int32   | 1–366       | Ordinal day of year |
| 4 | `hour`             | int32   | 0–23        | Hour of the day (24-hour) |
| 5 | `minute`           | int32   | 0–59        | Minute of the hour |
| 6 | `second`           | int32   | 0–59        | Second of the minute |
| 7 | `hundredthOfSecond`| int32   | 0–99        | Hundredths of a second |
| 8 | `length`           | double  | 1.0–39.8    | Vehicle length in metres |
| 9 | `lane`             | int32   | —           | Lane number |
| 10| `direction`        | int32   | 1–2         | 1 = address-increasing direction; 2 = address-decreasing direction |
| 11| `vehicleClass`     | int32   | 1–7         | See vehicle class table below |
| 12| `speed`            | int32   | 2–188       | Speed in km/h |
| 13| `faulty`           | int32   | 0–1         | 0 = valid record; 1 = faulty — filter to `faulty == 0` |
| 14| `totalTime`        | int32   | —           | Technical field |
| 15| `timeInterval`     | int32   | —           | Technical field (official spec has typo: "timeTnterval") |
| 16| `queueStart`       | int32   | —           | Technical field |

## Vehicle Classes

| Value | Code    | Description |
|-------|---------|-------------|
| 1     | HA-PA   | Car / delivery van |
| 2     | KAIP    | Lorry without trailer |
| 3     | BUS     | Bus |
| 4     | KAPP    | Semi-trailer truck |
| 5     | KATP    | Lorry + trailer |
| 6     | HA+PK   | Car + trailer |
| 7     | HA+AV   | Car + caravan |

## Example Row

```
109;25;164;0;0;7;270;3.800;1;1;1;76;0;727;1749772807090;0
```

Decoded:

- Station 109, 2025, day 164 (2025-06-13)
- Time: 00:00:07.270
- Length: 3.8 m, lane 1, direction 1
- Vehicle class 1 (car/van), speed 76 km/h
- Valid (faulty = 0)

## Notes

- Each row represents **one vehicle passage** (not an aggregated count)
- Timestamps use `hour`/`minute`/`second`/`hundredthOfSecond` — no absolute epoch in the timestamp columns
- `timeInterval` column 15 sometimes contains large epoch-like values; this appears to be a technical artefact
- Effective resolution for traffic flow aggregation: **per minute** (1440 bins/day) by counting rows per `(hour, minute)` bucket
