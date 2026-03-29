import json
import socket


def test_connection():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(("127.0.0.1", 5555))
        print("Connected successfully!")

        # Send a dummy payload
        payload = {
            "type": "heartbeat",
            "account_id": "12345",
            "timestamp": "2024-01-01T00:00:00Z",
        }
        s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        print("Payload sent!")
        s.close()
    except Exception as e:
        print(f"Connection failed: {e}")


if __name__ == "__main__":
    test_connection()
