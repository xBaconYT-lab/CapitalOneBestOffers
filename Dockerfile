# Dynamic version (server.py with auto-refresh) for any container host: Fly.io, Render, Railway, a VPS…
FROM python:3.12-slim
WORKDIR /app
COPY . .
ENV PORT=8787 REFRESH_HOURS=6 FEED_CALLS=8
EXPOSE 8787
CMD ["python", "server.py"]
