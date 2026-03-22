import asyncio
import websockets
import json

async def test_ws():
    uri = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    # Use 'additional_headers' for modern websockets library
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    
    print(f"Connecting to {uri}...")
    try:
        async with websockets.connect(uri, additional_headers=headers) as ws:
            print("✅ Connected!")
            
            sub_msg = {
                "type": "market",
                "assets_ids": ["55005064725926906068248348663116509417932324647288737689050979500578097013636"], # Real asset ID
                "custom_feature_enabled": True
            }
            await ws.send(json.dumps(sub_msg))
            print("Sent subscription request...")
            
            for _ in range(5):
                msg = await ws.recv()
                print(f"Received: {str(msg)[:100]}")
                await ws.send("PING")
                await asyncio.sleep(1)
                
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_ws())
