-- Enable pgvector extension for vector similarity search
CREATE EXTENSION IF NOT EXISTS vector;

-- Sidecar databases (WeKnora / Langfuse share the same Postgres instance).
-- This file runs only on first volume init.
CREATE DATABASE weknora;
CREATE DATABASE langfuse;
