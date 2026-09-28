# Invariants

## Architecture

- Keep clean architecture boundaries.
- Domain code must not import application, infrastructure, UI, or web modules.

## Technical Decisions

- Runtime memory and manually edited project settings must be stored separately from chat history.
- User profile and invariants are manually edited markdown files.

## Stack Constraints

- Keep the existing Python standard-library HTTP client for OpenAI API calls unless a task explicitly changes it.
- Keep PyQt as the desktop UI stack.

## Business Rules

- Clearing chat context must not delete manually edited profile or invariant files.
