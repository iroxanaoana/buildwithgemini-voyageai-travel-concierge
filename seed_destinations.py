"""Seed script for populating the 'destinations' Firestore collection.
"""
from google.cloud import firestore

# Hardcode the GCP Project ID as requested to prevent Agent Platform issues
PROJECT_ID = "qwiklabs-gcp-03-b53a60a6c37d"

SEED_DESTINATIONS = [
    {
        "id": "paris-france",
        "name": "Paris, France",
        "country": "France",
        "category": "Cultural",
        "budget_tier": "luxury",
        "description": "The City of Light, famous for world-class museums, iconic landmarks, and haute cuisine.",
        "best_season": "Spring",
        "rating": 4.8,
        "highlights": ["Eiffel Tower", "Louvre Museum", "Seine River Cruise"],
    },
    {
        "id": "tokyo-japan",
        "name": "Tokyo, Japan",
        "country": "Japan",
        "category": "Cultural & Modern",
        "budget_tier": "moderate",
        "description": "A bustling metropolis blending ultra-modern skyscrapers with historic temples and top-tier gastronomy.",
        "best_season": "Spring",
        "rating": 4.9,
        "highlights": ["Shibuya Crossing", "Senso-ji Temple", "Tsukiji Outer Market"],
    },
    {
        "id": "maui-hawaii",
        "name": "Maui, Hawaii, USA",
        "country": "USA",
        "category": "Beach & Tropical",
        "budget_tier": "luxury",
        "description": "A tropical paradise featuring pristine beaches, scenic highways, and volcanic landscapes.",
        "best_season": "Year-round",
        "rating": 4.7,
        "highlights": ["Road to Hana", "Haleakala National Park", "Kaanapali Beach"],
    },
    {
        "id": "rome-italy",
        "name": "Rome, Italy",
        "country": "Italy",
        "category": "Historical",
        "budget_tier": "moderate",
        "description": "The Eternal City, rich in ancient architecture, vibrant plazas, and authentic Italian dining.",
        "best_season": "Autumn",
        "rating": 4.8,
        "highlights": ["Colosseum", "Vatican Museums", "Trevi Fountain"],
    },
    {
        "id": "banff-canada",
        "name": "Banff, Alberta, Canada",
        "country": "Canada",
        "category": "Adventure & Nature",
        "budget_tier": "budget",
        "description": "A breathtaking mountain town surrounded by turquoise alpine lakes and majestic Rockies peaks.",
        "best_season": "Summer",
        "rating": 4.9,
        "highlights": ["Lake Louise", "Moraine Lake", "Banff Gondola"],
    },
]


def seed():
    db = firestore.Client(project=PROJECT_ID)
    collection_ref = db.collection("destinations")
    print(f"Seeding Firestore collection 'destinations' in project '{PROJECT_ID}'...")
    for data in SEED_DESTINATIONS:
        doc_id = data.pop("id")
        doc_ref = collection_ref.document(doc_id)
        doc_ref.set(data, merge=True)
        print(f"  ✓ Seeded document: {doc_id} -> {data['name']}")
    print("Seeding completed successfully!")


if __name__ == "__main__":
    seed()
