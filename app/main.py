from fastapi import FastAPI

app = FastAPI(title="Edu SDR", version="0.1.0")


@app.get("/health")
def health():
    return {"ok": True, "service": "edu-sdr", "version": "0.1.0"}
