--> Initial setup
--> Create Database
CREATE DATABASE IF NOT EXISTS AI_POLICY_NAVIGATOR;

--> Create Schema
CREATE SCHEMA IF NOT EXISTS AI_POLICY_NAVIGATOR.RAG;

--> Create an Internal Stage area where your PDFs can live 
CREATE OR REPLACE STAGE AI_POLICY_NAVIGATOR.RAG.PDF_STAGE   
    DIRECTORY = (ENABLE = TRUE)
    ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE');

--> Upload your PDFs and verify they are in the stage
LIST @AI_POLICY_NAVIGATOR.RAG.PDF_STAGE;