# SCMXpertLite

> **Intelligent Supply Chain Management** — Real-time shipment tracking with IoT telemetry, powered by FastAPI, Kafka, and MongoDB.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi&logoColor=white)
![Kafka](https://img.shields.io/badge/Kafka-4.0.0-231F20?logo=apachekafka&logoColor=white)
![MongoDB](https://img.shields.io/badge/MongoDB-Atlas-47A248?logo=mongodb&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)

---

## Features

- **Secure Authentication** — JWT-based login, Google OAuth2, reCAPTCHA protection, and OTP password reset via email
- **Shipment Management** — Full CRUD operations for shipments with route details, container info, and delivery tracking
- **Real-Time IoT Streaming** — Live sensor data (temperature, battery, location) streamed via Kafka + Server-Sent Events
- **Dashboard** — Glassmorphism dark-themed UI with animated particle background and live telemetry charts
- **Multi-Layer Security** — Bcrypt hashing, IP whitelisting, rate limiting, and password strength enforcement
- **Dockerized** — One-command deployment with Docker Compose

---

## Architecture

```text
┌─────────────────────────────────────────────────────────┐
│                    Frontend (Jinja2)                     │
│  login │ signup │ dashboard │ shipments │ data-stream    │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP / SSE
┌──────────────────────▼──────────────────────────────────┐
│               FastAPI Backend (:8000)                    │
│  routes/users.py │ routes/shipments.py │ routes/stream.py│
│  JWT Auth │ Google OAuth │ reCAPTCHA │ Rate Limiter      │
└────────┬────────────────────────────────┬───────────────┘
         │ Motor (async)                  │ AIOKafka
┌────────▼────────┐              ┌────────▼────────┐
│  MongoDB Atlas  │              │  Apache Kafka   │
│  • users        │              │  (KRaft mode)   │
│  • shipments    │◄─────────────│  topic:         │
│  • otps         │  consumer.py │  device_data    │
│  • device_stream│              │                 │
└─────────────────┘              └────────▲────────┘
                                          │ producer.py
                                 ┌────────┴────────┐
                                 │  IoT Simulator  │
                                 │  (every 3 sec)  │
                                 └─────────────────┘
```

---

## Quick Start

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- A [MongoDB Atlas](https://cloud.mongodb.com) cluster (free tier works)

### 1. Clone the repository

```bash
git clone https://github.com/KVISHNUREDDY333/SCM.git
cd SCM
```

### 2. Configure environment variables

Create a `.env` file in the project root:

```env
# MongoDB
MONGO_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/?appName=Cluster0&tls=true&tlsAllowInvalidCertificates=true
DB_NAME=mongo

# JWT
SECRET_KEY=your-secret-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Kafka
KAFKA_BOOTSTRAP_SERVERS=kafka:9092
KAFKA_TOPIC=device_data

# Google OAuth2
GOOGLE_CLIENT_ID=your-google-client-id
client_secret=your-google-client-secret

# reCAPTCHA
RECAPTCHA_SECRET_KEY=your-recaptcha-secret
RECAPTCHA_SITE_KEY=your-recaptcha-site-key

# SMTP (for OTP password reset)
MAIL_USERNAME=YourName
MAIL_PASS=your-app-password
MAIL_USER=your-email@gmail.com
MAIL_PORT=587
MAIL_SERVER=smtp.gmail.com

# Security
ALLOWED_IPS=*
GLOBAL_RATE_LIMIT=100/minute
```

### 3. Start with Docker Compose

```bash
docker-compose up --build -d
```

This starts 4 containers:

| Container | Purpose | Port |
| --- | --- | --- |
| `kafka` | Message broker (KRaft mode, no ZooKeeper) | 9092 |
| `fastapi-backend` | FastAPI web server | 8000 |
| `producer` | Simulates IoT sensor data to Kafka | - |
| `consumer` | Archives Kafka data to MongoDB | - |

### 4. Open the application

Navigate to [http://localhost:8000](http://localhost:8000) in your browser.

---

## Local Development (without Docker)

```bash
# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the FastAPI server
uvicorn backend.main:app --reload
```

> **Note:** For the real-time stream to work locally, you need Kafka running separately. Without it, the stream endpoint automatically falls back to **simulation mode**.

---

## Project Structure

```text
SCM/
├── backend/
│   ├── main.py                  # FastAPI app entry point
│   ├── auth/
│   │   ├── jwt_handler.py       # JWT sign/decode (HS256)
│   │   ├── google_verify.py     # Google OAuth2 token verification
│   │   └── recaptcha.py         # reCAPTCHA validation
│   ├── config/
│   │   ├── database.py          # MongoDB connection (Motor async)
│   │   └── limiter.py           # Rate limiter config (SlowAPI)
│   ├── middleware/
│   │   └── security.py          # JWTBearer guard + IP whitelisting
│   ├── models/
│   │   ├── user.py              # User & auth Pydantic schemas
│   │   └── shipment.py          # Shipment Pydantic schema
│   └── routes/
│       ├── users.py             # Auth endpoints (signup, login, OAuth, OTP reset)
│       ├── shipments.py         # Shipment CRUD endpoints
│       └── stream.py            # SSE real-time stream endpoint
├── frontend/
│   └── templates/
│       ├── base.html            # Master template (navbar, particle bg, auth JS)
│       ├── login.html           # Login with reCAPTCHA + Google Sign-In
│       ├── signup.html          # Registration with password validation
│       ├── dashboard.html       # Overview + recent shipments
│       ├── create_shipment.html # New shipment form
│       ├── my_shipments.html    # Shipment list with edit/delete
│       ├── data_stream.html     # Live IoT telemetry dashboard
│       ├── account.html         # User profile
│       ├── forgot_password.html # OTP-based password reset
│       └── error.html           # Custom 404 page
├── kafka/
│   ├── producer.py              # IoT data simulator to Kafka
│   └── consumer.py              # Kafka to MongoDB archiver
├── docker-compose.yml
├── Dockerfile                   # Backend container
├── Dockerfile.producer          # Producer container
├── Dockerfile.consumer          # Consumer container
├── requirements.txt
└── .env                         # Environment variables (not in git)
```

---

## API Endpoints

### Authentication (`/api/v1`)

| Method | Endpoint | Auth | Description |
| --- | --- | --- | --- |
| `POST` | `/signup` | No | Register a new user |
| `POST` | `/token` | No | Login (email + password + reCAPTCHA) |
| `POST` | `/auth/google` | No | Google OAuth2 login/auto-register |
| `POST` | `/forgot-password` | No | Request OTP via email |
| `POST` | `/reset-password` | No | Reset password with OTP |
| `GET` | `/me` | JWT | Get current user profile |

### Shipments (`/api/v1`)

| Method | Endpoint | Auth | Description |
| --- | --- | --- | --- |
| `POST` | `/shipments` | JWT | Create a new shipment |
| `GET` | `/shipments` | JWT | List all shipments |
| `PUT` | `/shipments/{number}` | JWT | Update a shipment |
| `DELETE` | `/shipments/{number}` | JWT | Delete a shipment |

### Streaming

| Method | Endpoint | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/events` | No | SSE stream of real-time IoT data |

---

## Security

| Layer | Implementation |
| --- | --- |
| **Password Hashing** | bcrypt via Passlib |
| **Password Policy** | Min 8 chars, 1 uppercase, 1 digit, 1 special character |
| **Authentication** | JWT (HS256, 100-min expiry) |
| **OAuth** | Google Sign-In (ID token verification) |
| **Bot Protection** | Google reCAPTCHA on login |
| **Rate Limiting** | SlowAPI - 100/min global, 5/min signup, 10/min login |
| **IP Whitelisting** | Configurable via `ALLOWED_IPS` env var |

---

## Database (MongoDB Atlas)

| Collection | Purpose |
| --- | --- |
| `users` | User accounts (email, hashed password, auth provider, last login) |
| `shipments` | Shipment records (number, route, device, goods type, delivery date) |
| `otps` | Temporary OTP codes for password reset (5-minute expiry) |
| `device_stream` | Archived IoT sensor data from Kafka consumer |

---

## UI Design

- **Theme:** Dark glassmorphism with cyber-blue (`#00d2ff`) accent
- **Font:** [Outfit](https://fonts.google.com/specimen/Outfit) (Google Fonts)
- **Background:** Animated particle network rendered on canvas
- **Components:** Glass cards with backdrop blur, gradient buttons, floating labels
- **Icons:** Font Awesome 6

---

## License

This project is for educational and demonstration purposes.

---

Built with FastAPI, Kafka, and MongoDB
