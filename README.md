# Wallet Service

A Django-based wallet service that supports deposits and scheduled withdrawals with asynchronous processing using Celery.

## Features

- Wallet deposit management
- Scheduled withdrawal processing
- Celery background jobs
- Transaction state management
- Concurrent transaction handling
- Third-party payment integration

## Tech Stack

- Django
- PostgreSQL
- Celery
- Redis

## Overview

This project implements a reliable wallet system where withdrawals are processed asynchronously at the requested execution time while maintaining wallet consistency and handling external service failures.