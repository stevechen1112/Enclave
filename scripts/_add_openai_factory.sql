INSERT INTO llm_factories (name, create_time, create_date, update_time, update_date, logo, tags, `rank`, status)
VALUES ('OpenAI', UNIX_TIMESTAMP()*1000, NOW(), UNIX_TIMESTAMP()*1000, NOW(), '', 'LLM,TEXT EMBEDDING,TTS,TEXT RE-RANK,SPEECH2TEXT,MODERATION', 999, '1');
SELECT name, status FROM llm_factories;
