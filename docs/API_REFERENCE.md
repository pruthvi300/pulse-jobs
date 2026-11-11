# API Reference

## Base URL

```
http://localhost:8000/api/v1
```

## Authentication

Currently, the API is unauthenticated. In production, you would add:
- API Keys in headers: `X-API-Key: your-key`
- JWT tokens: `Authorization: Bearer <token>`

---

## Endpoints

### Jobs

#### Create Job

Create a new background job for processing.

```
POST /jobs/
```

**Request Body:**

```json
{
  "task_name": "send_email",
  "payload": {
    "to": "user@example.com",
    "subject": "Welcome!",
    "body": "Hello from Pulse!"
  },
  "priority": "default",
  "idempotency_key": "welcome-email-user-123",
  "max_retries": 3
}
```

**Parameters:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `task_name` | string | Yes | Task to execute: `send_email`, `generate_report`, `process_webhook`, `process_image` |
| `payload` | object | No | Arguments to pass to the task |
| `priority` | string | No | `critical`, `high`, `default`, `low`. Default: `default` |
| `idempotency_key` | string | No | Unique key to prevent duplicate jobs |
| `max_retries` | integer | No | Maximum retry attempts (0-10). Default: 3 |

**Response (201 Created):**

```json
{
  "id": 1,
  "task_name": "send_email",
  "payload": {
    "to": "user@example.com",
    "subject": "Welcome!",
    "body": "Hello from Pulse!"
  },
  "status": "pending",
  "priority": "default",
  "attempts": 0,
  "max_retries": 3,
  "result": null,
  "error_message": null,
  "created_at": "2024-01-15T10:30:00Z",
  "started_at": null,
  "completed_at": null
}
```

**Idempotency:**

If you submit a job with an `idempotency_key` that already exists, the API returns the existing job with **200 OK** (instead of 201) and does not enqueue anything. This is safe for client retries, including two identical requests racing each other.

**Payload validation:** each task has its own schema (see Task Payloads). Missing fields, unknown fields or invalid values return **422** before anything is queued.

**Queue unavailable:** if the broker can't be reached, the job is stored as `failed` with the reason and the API returns **503**.

---

#### Get Job

Retrieve a specific job by ID. Workers update the job row as it runs, so this is a plain database read.

```
GET /jobs/{job_id}
```

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `job_id` | integer | The job's unique ID |

**Response (200 OK):**

```json
{
  "id": 1,
  "task_name": "send_email",
  "payload": {...},
  "status": "completed",
  "priority": "default",
  "attempts": 1,
  "max_retries": 3,
  "result": {
    "status": "sent",
    "recipient": "user@example.com",
    "message_id": "msg_1234"
  },
  "error_message": null,
  "created_at": "2024-01-15T10:30:00Z",
  "started_at": "2024-01-15T10:30:01Z",
  "completed_at": "2024-01-15T10:30:03Z"
}
```

**Status Values:**

| Status | Description |
|--------|-------------|
| `pending` | Job is queued, waiting for a worker |
| `running` | Worker is executing the job |
| `completed` | Job finished successfully |
| `failed` | Permanent error or crash; not retried automatically (replay with POST /retry) |
| `retrying` | Job failed and is scheduled for retry |
| `dead_letter` | Transient errors exhausted the job's `max_retries` (replay with POST /retry) |

---

#### List Jobs

Retrieve a paginated list of jobs with optional filtering.

```
GET /jobs/
```

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `status` | string | - | Filter by status |
| `task_name` | string | - | Filter by task name |
| `page` | integer | 1 | Page number (1-indexed) |
| `page_size` | integer | 20 | Items per page (max 100) |

**Example:**

```
GET /jobs/?status=failed&page=1&page_size=10
```

**Response (200 OK):**

```json
{
  "jobs": [
    {
      "id": 5,
      "task_name": "send_email",
      "status": "failed",
      ...
    },
    ...
  ],
  "total": 25,
  "page": 1,
  "page_size": 10
}
```

---

#### Get Statistics

Retrieve aggregate job statistics for the dashboard.

```
GET /jobs/stats/summary
```

**Response (200 OK):**

```json
{
  "total_jobs": 151,
  "pending": 5,
  "running": 2,
  "retrying": 1,
  "completed": 130,
  "failed": 10,
  "dead_letter": 3
}
```

---

#### Retry Job

Retry a failed or dead-letter job.

```
POST /jobs/{job_id}/retry
```

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `job_id` | integer | The job's unique ID |

**Requirements:**
- Job must be in `failed` or `dead_letter` status

**Response (200 OK):**

Returns the job with reset status (now `pending`), `attempts` reset to 0 and a new `celery_task_id`.

**Error Response (409 Conflict):**

```json
{
  "detail": "Only failed or dead-letter jobs can be retried (status: completed)"
}
```

---

## Task Payloads

### send_email

Send an email to a recipient.

```json
{
  "to": "recipient@example.com",
  "subject": "Email Subject",
  "body": "Email body content"
}
```

### generate_report

Generate a report of the specified type.

```json
{
  "report_type": "monthly",
  "params": {
    "month": "January",
    "year": 2024
  }
}
```

### process_webhook

Deliver a webhook payload to an external URL.

```json
{
  "webhook_url": "https://api.example.com/webhooks",
  "payload": {
    "event": "order.created",
    "data": {...}
  }
}
```

### process_image

Process an image with specified operations.

```json
{
  "image_url": "https://example.com/image.jpg",
  "operations": ["resize", "compress", "thumbnail"]
}
```

---

## Error Responses

### 400 Bad Request

```json
{
  "detail": "Unknown task: invalid_task. Available: ['send_email', 'generate_report', 'process_webhook', 'process_image']"
}
```

### 404 Not Found

```json
{
  "detail": "Job 999 not found"
}
```

### 422 Validation Error

```json
{
  "detail": [
    {
      "loc": ["body", "task_name"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

---

## Rate Limiting (Future)

In production, rate limiting would be applied:

```
Headers:
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1642262400
```

When exceeded:

```
429 Too Many Requests
{
  "detail": "Rate limit exceeded. Try again in 60 seconds."
}
```
