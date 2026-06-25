# BallKnowledge Data Service – API Reference

Base URL: `http://localhost:8000/api/v1`

All request/response bodies are JSON. All path parameters are URL-encoded where applicable.

---

## Table of Contents

1. [Register Team](#1-register-team)
2. [Register Squad Entry](#2-register-squad-entry)
3. [Resolve Player Identity](#3-resolve-player-identity)

---

## 1. Register Team

Register a team (with its starting formation) for a given match. If the `(match_id, team_id)` pair already exists, the endpoint is a no-op and returns the existing record's ID.

### Request

```
POST /api/v1/matches/{match_id}/teams
```

| Parameter   | Location | Type   | Required | Description                       |
|-------------|----------|--------|----------|-----------------------------------|
| `match_id`  | path     | string | ✅       | Unique identifier for the match   |
| `team_id`   | body     | int    | ✅       | Numeric ID of the team            |
| `formation` | body     | string | ✅       | Formation string (e.g. `"4-3-3"`) |

#### Example Request Body

```json
{
  "team_id": 101,
  "formation": "4-3-3"
}
```

### Responses

| Status | Body                                    | Description                                       |
|--------|-----------------------------------------|---------------------------------------------------|
| `200`  | `{"status": "created", "id": 1}`        | Team registered successfully                      |
| `200`  | `{"status": "already_exists", "id": 1}` | Team already registered; no change made           |

#### Example Success Response

```json
{
  "status": "created",
  "id": 1
}
```

---

## 2. Register Squad Entry

Add a player (squad entry) to a registered team for a specific match. The team **must already exist** (via [Register Team](#1-register-team)) before entries can be added. If a squad entry with the same jersey number already exists for the team, the endpoint is a no-op.

### Request

```
POST /api/v1/matches/{match_id}/teams/{team_id}/squad
```

| Parameter       | Location | Type    | Required | Description                                                                |
|-----------------|----------|---------|----------|----------------------------------------------------------------------------|
| `match_id`      | path     | string  | ✅       | Unique identifier for the match                                            |
| `team_id`       | path     | int     | ✅       | Numeric ID of the team (must be registered first)                          |
| `jersey_number` | body     | int     | ✅       | Player's jersey number                                                     |
| `entity_id`     | body     | int     | ❌       | Resolved player entity ID (can be `null` if identity is unknown)           |
| `role`          | body     | string  | ✅       | Player's role (e.g. `"goalkeeper"`, `"defender"`, `"midfielder"`, `"attacker"`, `"unknown"`) |
| `is_starter`    | body     | boolean | ✅       | Whether the player is in the starting lineup                               |

#### Example Request Body

```json
{
  "jersey_number": 10,
  "entity_id": null,
  "role": "midfielder",
  "is_starter": true
}
```

### Responses

| Status | Body                                                      | Description                                            |
|--------|-----------------------------------------------------------|--------------------------------------------------------|
| `200`  | `{"status": "created"}`                                   | Squad entry registered successfully                    |
| `200`  | `{"status": "already_exists"}`                            | Jersey number already exists for this team; no change  |
| `404`  | `{"detail": "Team not found for this match"}`             | Team has not been registered for this match yet        |

#### Example Success Response

```json
{
  "status": "created"
}
```

#### Example Error Response

```json
{
  "detail": "Team not found for this match"
}
```

---

## 3. Resolve Player Identity

Update the `entity_id` of an existing squad entry identified by jersey number. Used when a player's identity (initially unknown) is resolved — for example, by a downstream recognition pipeline.

> **Important:** This endpoint **only updates** existing squad entries. It will never create a new record. Both the team and the jersey number must already exist.

### Request

```
PATCH /api/v1/matches/{match_id}/teams/{team_id}/squad/{jersey_number}/identity
```

| Parameter       | Location | Type   | Required | Description                           |
|-----------------|----------|--------|----------|---------------------------------------|
| `match_id`      | path     | string | ✅       | Unique identifier for the match       |
| `team_id`       | path     | int    | ✅       | Numeric ID of the team                |
| `jersey_number` | path     | int    | ✅       | Jersey number of the player to update |
| `entity_id`     | body     | int    | ✅       | The resolved player entity ID         |

#### Example Request Body

```json
{
  "entity_id": 9876
}
```

### Responses

| Status | Body                    | Description                                                        |
|--------|-------------------------|--------------------------------------------------------------------|
| `200`  | `{"status": "success"}` | Identity resolved and `entity_id` updated successfully             |
| `404`  | `{"detail": "..."}`     | Team not found **or** jersey number not found in this team's squad |

#### Example Success Response

```json
{
  "status": "success"
}
```

#### Example Error Responses

```json
{
  "detail": "Team 101 not found for match match_abc"
}
```

```json
{
  "detail": "Jersey #99 not found in squad for team 101 in match match_abc"
}
```

---

## Data Models

### TeamInfo

Stored in the `team_info` table.

| Field       | Type    | Constraints               | Description                     |
|-------------|---------|---------------------------|---------------------------------|
| `id`        | integer | Primary key, auto-increment | Internal surrogate key        |
| `match_id`  | string  | Not null, indexed         | Match this team belongs to      |
| `team_id`   | integer | Not null                  | External team identifier        |
| `formation` | string  | Not null                  | Team formation (e.g. `"4-3-3"`) |

**Unique constraint:** `(match_id, team_id)`

---

### SquadEntry

Stored in the `squad_entries` table.

| Field            | Type    | Constraints                  | Description                                    |
|------------------|---------|------------------------------|------------------------------------------------|
| `id`             | integer | Primary key, auto-increment  | Internal surrogate key                         |
| `team_info_id`   | integer | Foreign key → `team_info.id` | Links to the parent team record                |
| `jersey_number`  | integer | Not null                     | Player's jersey number                         |
| `entity_id`      | integer | Nullable                     | Resolved player entity ID; `null` if unknown   |
| `role`           | string  | Not null                     | Player's role (free-form string)               |
| `is_starter`     | boolean | Not null                     | Whether the player started the match           |

**Unique constraint:** `(team_info_id, jersey_number)`

---

## Typical Usage Flow

```
1. POST  /api/v1/matches/{match_id}/teams                                              → Register home team
2. POST  /api/v1/matches/{match_id}/teams                                              → Register away team
3. POST  /api/v1/matches/{match_id}/teams/{team_id}/squad                              → Add players to home team
4. POST  /api/v1/matches/{match_id}/teams/{team_id}/squad                              → Add players to away team
5. PATCH /api/v1/matches/{match_id}/teams/{team_id}/squad/{jersey_number}/identity     → Resolve identities as they are detected
```

---

## Notes

- **`role` is a free-form string.** The API does not enforce an enum. Recommended values: `"goalkeeper"`, `"defender"`, `"midfielder"`, `"attacker"`, `"unknown"`.
- **Idempotency:** `POST /teams` and `POST /squad` are safe to call multiple times — they will not create duplicates.
- **Strict identity resolution:** `PATCH .../identity` returns `404` if the jersey does not already exist in the squad. It never creates ghost rows.
- **URL encoding:** When `match_id` contains special characters (spaces, slashes, etc.), ensure it is properly URL-encoded in the path. Avoid copy-pasting URLs from rich-text editors — invisible trailing characters (e.g. `%0A`) will cause `404` errors.
