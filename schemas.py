"""
Database Schemas for Online Printing App

Each Pydantic model generally maps to a MongoDB collection (lowercased name).
"""
from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field, EmailStr


class Address(BaseModel):
    label: Optional[str] = Field(None, description="Label like Home/Office")
    address_line: str
    city: str
    pincode: str
    is_default: bool = False


class User(BaseModel):
    full_name: str
    mobile: str
    email: EmailStr
    password_hash: str
    addresses: List[Address] = []


class Session(BaseModel):
    user_id: str
    token: str
    expires_at: int  # epoch seconds


# Cart and order related
PrintSize = Literal["A4", "A3", "A5"]
PaperQuality = Literal[
    "80_GSM",
    "100_GSM",
    "130_GSM",
    "170_GSM",
    "250_GSM",
    "300_GSM_MATTE",
    "300_GSM_GLOSS",
]
Sides = Literal["single", "double"]


class FileRef(BaseModel):
    filename: str
    path: str
    size: int
    mime: Optional[str] = None


class AddOns(BaseModel):
    spiral_binding: Optional[Literal["up_to_80", "81_150"]] = None
    lamination: Optional[Literal["ID", "A4", "A3"]] = None


class DocumentPrintOptions(BaseModel):
    color: Literal["bw", "colour"]
    size: Literal["A4", "A3"]
    gsm: Literal[80, 100, 130]
    sides: Sides
    files: List[FileRef]


class VisitingCardOptions(BaseModel):
    card_type: Literal["personal", "office"]
    paper: Literal["economy_250_matte", "premium_300_matte", "premium_300_gloss"]
    quantity: Literal[50, 100]
    design: Literal["ready_design", "logo_plus_text"]
    files: List[FileRef] = []


class LetterheadOptions(BaseModel):
    gsm: Literal[100, 130]
    quantity: Literal[100, 200]
    design: Literal["ready_design", "logo_plus_text"]
    files: List[FileRef] = []


class EnvelopeOptions(BaseModel):
    type: Literal["standard_80", "premium_100"]
    size: Literal["DL"]
    quantity: Literal[100, 200]
    files: List[FileRef] = []


class FlyerOptions(BaseModel):
    size: Literal["A5", "A4"]
    gsm: Literal[130]
    quantity: Literal[50, 100]
    files: List[FileRef]


class PosterOptions(BaseModel):
    size: Literal["A3"]
    gsm: Literal[170]
    quantity: Literal[1, 10]
    files: List[FileRef]


class MugOptions(BaseModel):
    print_area: Literal["one_side", "wrap"]
    quantity: Literal[1, 2, 4]
    images: List[FileRef] = []
    text: Optional[str] = None


class CartItem(BaseModel):
    product: Literal[
        "document_printing",
        "visiting_cards",
        "letterheads",
        "envelopes",
        "flyers",
        "posters",
        "custom_mug",
    ]
    options: Dict[str, Any]
    addons: Optional[AddOns] = None
    quantity: int = 1
    unit_price: Optional[float] = None  # computed by backend
    line_total: Optional[float] = None  # computed by backend


class Order(BaseModel):
    user_id: str
    items: List[CartItem]
    pricing_breakdown: Dict[str, Any]
    total: float
    status: Literal["Placed", "In Printing", "Ready for Dispatch", "Completed"] = "Placed"
    address: Address
    contains_office_visiting_cards: bool = False
    whatsapp_link: Optional[str] = None
