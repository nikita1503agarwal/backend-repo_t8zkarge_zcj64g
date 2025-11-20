import os
import hashlib
import secrets
from urllib.parse import quote_plus
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from bson import ObjectId

from database import db, create_document
from schemas import (
    User, Address, Session, CartItem, Order, FileRef
)

app = FastAPI(title="Printing & Custom Mugs API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------- Helpers -----------------------------

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def generate_token() -> str:
    return secrets.token_hex(24)


def to_object_id(value):
    try:
        return ObjectId(value)
    except Exception:
        return None


def auth_user(token: Optional[str]):
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    sess = db.session.find_one({"token": token})
    if not sess:
        raise HTTPException(status_code=401, detail="Invalid session")
    oid = to_object_id(sess.get("user_id"))
    user = db.user.find_one({"_id": oid}) if oid else None
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


# ----------------------------- Auth Routes -----------------------------

class RegisterPayload(BaseModel):
    full_name: str
    mobile: str
    email: EmailStr
    password: str
    address_line: str
    city: str
    pincode: str


@app.post("/auth/register")
def register(payload: RegisterPayload):
    # Check existing
    if db.user.find_one({"$or": [{"email": payload.email}, {"mobile": payload.mobile}]}):
        raise HTTPException(status_code=400, detail="Account already exists")

    address: Address = Address(
        label="Default",
        address_line=payload.address_line,
        city=payload.city,
        pincode=payload.pincode,
        is_default=True,
    )

    user = User(
        full_name=payload.full_name,
        mobile=payload.mobile,
        email=payload.email,
        password_hash=hash_password(payload.password),
        addresses=[address],
    )
    user_id = create_document("user", user)

    token = generate_token()
    session = Session(user_id=user_id, token=token, expires_at=0)
    create_document("session", session)

    return {"token": token, "user": {"id": user_id, "full_name": user.full_name, "email": user.email, "mobile": user.mobile, "addresses": [address.model_dump()]}}


class LoginPayload(BaseModel):
    identifier: str  # email or mobile
    password: str


@app.post("/auth/login")
def login(payload: LoginPayload):
    hashed = hash_password(payload.password)
    user = db.user.find_one({
        "$and": [
            {"password_hash": hashed},
            {"$or": [{"email": payload.identifier}, {"mobile": payload.identifier}]}
        ]
    })
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = generate_token()
    session = Session(user_id=str(user["_id"]), token=token, expires_at=0)
    create_document("session", session)

    return {"token": token, "user": {"id": str(user["_id"]), "full_name": user.get("full_name"), "email": user.get("email"), "mobile": user.get("mobile"), "addresses": user.get("addresses", [])}}


@app.get("/me")
def me(token: Optional[str] = None):
    user = auth_user(token)
    return {
        "id": str(user["_id"]),
        "full_name": user.get("full_name"),
        "email": user.get("email"),
        "mobile": user.get("mobile"),
        "addresses": user.get("addresses", []),
    }


# ----------------------------- Uploads -----------------------------
UPLOAD_DIR = os.path.join(os.getcwd(), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.post("/upload")
async def upload_files(token: Optional[str] = None, files: List[UploadFile] = File(...)):
    _ = auth_user(token)  # ensure logged in
    saved: List[FileRef] = []
    for f in files:
        ext = os.path.splitext(f.filename)[1]
        name = secrets.token_hex(8) + ext
        dest = os.path.join(UPLOAD_DIR, name)
        with open(dest, "wb") as out:
            out.write(await f.read())
        saved.append(FileRef(filename=f.filename, path=f"/uploads/{name}", size=os.path.getsize(dest), mime=f.content_type))
    return {"files": [s.model_dump() for s in saved]}


@app.get("/uploads/{filename}")
def uploaded_file(filename: str):
    # Static serving simple response
    path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Not found")
    return JSONResponse({"path": f"/uploads/{filename}"})


# ----------------------------- Pricing Logic -----------------------------

PLATFORM_FEE = 10
DELIVERY_THRESHOLD = 300
DELIVERY_FEE = 35


def price_document_printing(opts: Dict[str, Any]) -> float:
    color = opts.get("color")  # bw or colour
    size = opts.get("size")     # A4 or A3
    gsm = int(opts.get("gsm"))  # 80/100/130
    pages = int(opts.get("pages", 1))
    prices = {
        ("bw", "A4", 80): 3,
        ("bw", "A4", 100): 4,
        ("bw", "A4", 130): 5,
        ("bw", "A3", 80): 8,
        ("bw", "A3", 100): 10,
        ("bw", "A3", 130): 12,
        ("colour", "A4", 80): 10,
        ("colour", "A4", 100): 12,
        ("colour", "A4", 130): 15,
        ("colour", "A3", 80): 25,
        ("colour", "A3", 100): 30,
        ("colour", "A3", 130): 35,
    }
    per_page = prices.get((color, size, gsm))
    if per_page is None:
        raise HTTPException(status_code=400, detail="Invalid options")
    base = per_page * pages
    return float(base)


def price_visiting_cards(opts: Dict[str, Any]) -> float:
    paper = opts.get("paper")
    qty = int(opts.get("quantity"))
    if paper == "economy_250_matte":
        return 150.0 if qty == 50 else 250.0
    if paper in ("premium_300_matte", "premium_300_gloss"):
        return 250.0 if qty == 50 else 400.0
    raise HTTPException(status_code=400, detail="Invalid options")


def price_letterheads(opts: Dict[str, Any]) -> float:
    gsm = int(opts.get("gsm"))
    qty = int(opts.get("quantity"))
    if gsm == 100:
        return 200.0 if qty == 100 else 350.0
    if gsm == 130:
        return 260.0 if qty == 100 else 450.0
    raise HTTPException(status_code=400, detail="Invalid options")


def price_envelopes(opts: Dict[str, Any]) -> float:
    typ = opts.get("type")
    qty = int(opts.get("quantity"))
    if typ == "standard_80":
        return 200.0 if qty == 100 else 350.0
    if typ == "premium_100":
        return 260.0 if qty == 100 else 450.0
    raise HTTPException(status_code=400, detail="Invalid options")


def price_flyers(opts: Dict[str, Any]) -> float:
    size = opts.get("size")
    qty = int(opts.get("quantity"))
    if size == "A5":
        return 250.0 if qty == 50 else 400.0
    if size == "A4":
        return 350.0 if qty == 50 else 600.0
    raise HTTPException(status_code=400, detail="Invalid options")


def price_posters(opts: Dict[str, Any]) -> float:
    qty = int(opts.get("quantity"))
    return 80.0 if qty == 1 else 700.0


def price_mugs(opts: Dict[str, Any]) -> float:
    qty = int(opts.get("quantity"))
    if qty == 1:
        return 299.0
    if qty == 2:
        return 550.0
    if qty == 4:
        return 1040.0
    raise HTTPException(status_code=400, detail="Invalid options")


def price_addons(addons: Optional[Dict[str, Any]], base_product: str, opts: Dict[str, Any]) -> float:
    if not addons:
        return 0.0
    total = 0.0
    spiral = addons.get("spiral_binding")
    if spiral and base_product == "document_printing":
        if spiral == "up_to_80":
            total += 30.0
        elif spiral == "81_150":
            total += 40.0
    lam = addons.get("lamination")
    if lam:
        if lam == "ID":
            total += 15.0
        elif lam == "A4":
            total += 40.0
        elif lam == "A3":
            total += 60.0
    return total


@app.post("/price/compute")
def compute_price(items: List[CartItem]):
    line_items = []
    subtotal = 0.0
    contains_office = False
    for it in items:
        prod = it.product
        opts = it.options or {}
        qty = int(it.quantity)
        unit = 0.0
        if prod == "document_printing":
            unit = price_document_printing(opts)
        elif prod == "visiting_cards":
            unit = price_visiting_cards(opts)
            if opts.get("card_type") == "office":
                contains_office = True
        elif prod == "letterheads":
            unit = price_letterheads(opts)
        elif prod == "envelopes":
            unit = price_envelopes(opts)
        elif prod == "flyers":
            unit = price_flyers(opts)
        elif prod == "posters":
            unit = price_posters(opts)
        elif prod == "custom_mug":
            unit = price_mugs(opts)
        else:
            raise HTTPException(status_code=400, detail="Unknown product")
        addon_cost = price_addons(it.addons.model_dump() if it.addons else None, prod, opts)
        line_total = (unit + addon_cost) * qty
        subtotal += line_total
        line_items.append({
            "product": prod,
            "options": opts,
            "quantity": qty,
            "unit_price": unit,
            "addon_cost": addon_cost,
            "line_total": line_total,
        })

    platform_fee = PLATFORM_FEE
    delivery_fee = 0 if subtotal > DELIVERY_THRESHOLD else DELIVERY_FEE
    total = subtotal + platform_fee + delivery_fee

    return {
        "items": line_items,
        "subtotal": subtotal,
        "platform_fee": platform_fee,
        "delivery_fee": delivery_fee,
        "total": total,
        "contains_office_visiting_cards": contains_office,
    }


# ----------------------------- Orders -----------------------------

class CheckoutPayload(BaseModel):
    items: List[CartItem]
    address: Address
    payment_method: str
    token: Optional[str] = None


@app.post("/orders")
def place_order(payload: CheckoutPayload):
    user = auth_user(payload.token)
    pricing = compute_price(payload.items)

    order_model = Order(
        user_id=str(user["_id"]),
        items=payload.items,
        pricing_breakdown={
            "items": pricing["items"],
            "subtotal": pricing["subtotal"],
            "platform_fee": pricing["platform_fee"],
            "delivery_fee": pricing["delivery_fee"],
        },
        total=pricing["total"],
        address=payload.address,
        contains_office_visiting_cards=pricing["contains_office_visiting_cards"],
    )

    order_id = create_document("order", order_model)

    whatsapp_link = None
    if pricing["contains_office_visiting_cards"]:
        admin_number = os.getenv("ADMIN_WHATSAPP", "+911234567890")
        text = f"Order ID: {order_id}%0AUser: {user.get('full_name')} ({user.get('mobile')})%0AProduct: Office visiting card%0ADetails: see admin panel"
        whatsapp_link = f"https://wa.me/{admin_number.replace('+', '')}?text={text}"
        db.order.update_one({"_id": to_object_id(order_id)}, {"$set": {"whatsapp_link": whatsapp_link}})

    return {
        "order_id": order_id,
        "total": pricing["total"],
        "status": "Order placed",
        "whatsapp_link": whatsapp_link,
        "message": "We’ll confirm your office visiting card design with you on WhatsApp before printing." if pricing["contains_office_visiting_cards"] else None,
    }


@app.get("/orders")
def list_orders(token: Optional[str] = None):
    user = auth_user(token)
    docs = list(db.order.find({"user_id": str(user["_id"])}).sort("created_at", -1))
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return {"orders": docs}


@app.get("/orders/{order_id}")
def get_order(order_id: str, token: Optional[str] = None):
    user = auth_user(token)
    doc = db.order.find_one({"_id": to_object_id(order_id), "user_id": str(user["_id"])})
    if not doc:
        raise HTTPException(status_code=404, detail="Order not found")
    doc["id"] = str(doc.pop("_id"))
    return doc


@app.get("/")
def read_root():
    return {"message": "Printing API running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        from database import db as _db
        if _db is not None:
            response["database"] = "✅ Connected & Working"
            response["database_url"] = "✅ Set"
            response["database_name"] = _db.name
            response["connection_status"] = "Connected"
            response["collections"] = _db.list_collection_names()
    except Exception as e:
        response["database"] = f"Error: {str(e)}"
    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
