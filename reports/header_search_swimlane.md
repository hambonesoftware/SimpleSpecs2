# Header Search Function Flow

This document summarises the end-to-end flow for the header search feature and provides a Mermaid swimlane diagram that renders without syntax errors.

## Overview
- **User interaction** – the header search begins when the user chooses a document and presses **Start search** in the header panel.
- **Frontend logic** – `refreshHeaders` coordinates validation, busy-state toggles, and delegates the API call to `fetchHeaders`.
- **Backend orchestration** – `compute_headers` validates the request, selects parsing modes, and invokes `extract_headers_and_chunks` which runs the multi-stage extraction/alignment pipeline.
- **Response handling** – the backend persists section metadata and sends the outline, raw response, and trace information back to the client so the UI can render the results or surface recovery messaging.

## Swimlane Diagram
```mermaid
flowchart TB
    subgraph User[User]
        userClick[Click "Start search" button]
    end

    subgraph FrontendUI[Frontend UI (app.js)]
        refresh[refreshHeaders\n• validate selection\n• set busy/loading states]
        render[Render outline + raw panels\nUpdate mode tag and toasts]
        fallback[Restore previous outline\nor show error panel]
    end

    subgraph FrontendAPI[Frontend API client (api.js)]
        callFetch[fetchHeaders(documentId)\nPOST /api/headers/{id}]
    end

    subgraph BackendAPI[Backend API (headers.py)]
        validate[compute_headers\nValidate document and choose mode]
        parseLLM[parse_pdf + extract_headers\nProduce native outline]
        orchestrate[extract_headers_and_chunks\nAlign headers and sections]
        respond[Persist sections\nUpdate SimpleHeadersState\nBuild payload]
    end

    subgraph BackendServices[Header services]
        cache[get_cached_artifact?]
        llm[LLM extraction fallbacks\n(full → strict → vector → sequential)]
        sectionize[single_chunks_from_headers\n+ build_and_store_sections]
    end

    userClick --> refresh
    refresh --> callFetch
    callFetch --> validate
    validate --> parseLLM
    parseLLM --> orchestrate
    orchestrate --> cache
    cache --> llm
    llm --> sectionize
    sectionize --> respond
    respond --> render
    respond --> fallback
```
