from fastapi import FastAPI

app = FastAPI()


@app.post("/api/login")
def login() -> dict[str, str]:
    return {"message": "Hello, world!"}
