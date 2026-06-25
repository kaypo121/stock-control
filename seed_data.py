import sys
from datetime import datetime, timedelta
from app.database import engine, Base, SessionLocal
from app.models.stock_models import Farmer, Product, Warehouse, StockTransaction, StockBalance
from app.services.stock_service import StockService
from app.repositories.stock_repo import StockRepository

def seed_db():
    print("Initialising database tables...")
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    repo = StockRepository(db)
    service = StockService(db)
    
    try:
        # Check if already seeded
        if db.query(Farmer).first():
            print("Database already contains data. Skipping seeding.")
            return

        print("Seeding Farmers...")
        farmers_data = [
            {"full_name": "Kofi Mensah", "phone_number": "+233241112222", "region": "Bono", "district": "Sunyani Municipal", "farm_name": "Mensah Farms"},
            {"full_name": "Kojo Annan", "phone_number": "+233243334444", "region": "Ashanti", "district": "Ejura Sekyedumase", "farm_name": "Annan Cocoa Enterprise"},
            {"full_name": "Ama Serwaa", "phone_number": "+233245556666", "region": "Volta", "district": "Ho Municipal", "farm_name": "Volta Roots Ltd"},
            {"full_name": "Abena Osei", "phone_number": "+233247778888", "region": "Greater Accra", "district": "Ada East", "farm_name": "Coastal Farm Group"}
        ]
        farmers = []
        for f in farmers_data:
            farmers.append(repo.create_farmer(**f))

        print("Seeding Products...")
        products_data = [
            {"product_name": "White Maize", "category": "Grains", "unit": "kg", "description": "Standard white grain maize"},
            {"product_name": "Maize Yellow", "category": "Grains", "unit": "kg", "description": "Yellow grain maize for poultry and feed"},
            {"product_name": "Rice Local", "category": "Grains", "unit": "kg", "description": "Local brown/white husked rice"},
            {"product_name": "Cassava", "category": "Roots & Tubers", "unit": "kg", "description": "Fresh cassava tubers"},
            {"product_name": "Yam Puna", "category": "Roots & Tubers", "unit": "piece", "description": "Premium Puna yam tubers"},
            {"product_name": "Tomato Local", "category": "Vegetables", "unit": "crate", "description": "Local garden fresh tomatoes"},
            {"product_name": "Cocoa Beans", "category": "Cash Crops", "unit": "kg", "description": "Dried fermented cocoa beans"}
        ]
        products = {}
        for p in products_data:
            prod = repo.create_product(**p)
            products[prod.product_name] = prod

        print("Seeding Warehouses...")
        warehouses_data = [
            {"warehouse_name": "Sunyani Central Silo", "region": "Bono", "district": "Sunyani Municipal", "capacity": 10000.0},
            {"warehouse_name": "Ejura Grain Depot", "region": "Ashanti", "district": "Ejura Sekyedumase", "capacity": 50000.0},
            {"warehouse_name": "Ho Cooperative Vault", "region": "Volta", "district": "Ho Municipal", "capacity": 5000.0},
            {"warehouse_name": "Agbogbloshie Market Shed", "region": "Greater Accra", "district": "Accra Metropolitan", "capacity": 12000.0}
        ]
        warehouses = {}
        for w in warehouses_data:
            wh = repo.create_warehouse(**w)
            warehouses[wh.warehouse_name] = wh

        print("Recording Initial Movements...")
        # 1. Kofi Mensah stocks in 200 bags of Maize Yellow at Ejura Grain Depot (converts to 10000 kg since 1 bag = 50 kg)
        service.record_movement(
            farmer_id=farmers[0].farmer_id,
            product_id=products["Maize Yellow"].product_id,
            warehouse_id=warehouses["Ejura Grain Depot"].warehouse_id,
            transaction_type="STOCK_IN",
            quantity=200.0,
            unit="bags",
            transaction_date=datetime.utcnow() - timedelta(days=45),
            reference_note="First harvest drop"
        )

        # 2. Kofi Mensah sells (stock out) 50 bags (2500 kg)
        service.record_movement(
            farmer_id=farmers[0].farmer_id,
            product_id=products["Maize Yellow"].product_id,
            warehouse_id=warehouses["Ejura Grain Depot"].warehouse_id,
            transaction_type="STOCK_OUT",
            quantity=50.0,
            unit="bags",
            transaction_date=datetime.utcnow() - timedelta(days=30),
            reference_note="Sale to wholesale vendor"
        )

        # Let's set a reorder level for Kofi's Maize Yellow to test reorder alerts
        bal_kofi_maize = repo.get_balance(
            farmers[0].farmer_id, 
            products["Maize Yellow"].product_id, 
            warehouses["Ejura Grain Depot"].warehouse_id
        )
        bal_kofi_maize.reorder_level = 8000.0  # Current stock is 7500kg (150 bags), so this triggers LOW_STOCK!
        db.commit()
        service._check_alerts(bal_kofi_maize)

        # 3. Kojo Annan stocks in Cocoa Beans at Ejura Grain Depot
        service.record_movement(
            farmer_id=farmers[1].farmer_id,
            product_id=products["Cocoa Beans"].product_id,
            warehouse_id=warehouses["Ejura Grain Depot"].warehouse_id,
            transaction_type="STOCK_IN",
            quantity=2500.0,
            unit="kg",
            transaction_date=datetime.utcnow() - timedelta(days=20),
            reference_note="Seeded stock"
        )

        # 4. Ama Serwaa stocks in 1200 Yam tubers at Ho Cooperative Vault
        service.record_movement(
            farmer_id=farmers[2].farmer_id,
            product_id=products["Yam Puna"].product_id,
            warehouse_id=warehouses["Ho Cooperative Vault"].warehouse_id,
            transaction_type="STOCK_IN",
            quantity=1200.0,
            unit="piece",
            transaction_date=datetime.utcnow() - timedelta(days=15),
            reference_note="Yam harvest loading"
        )

        # 5. Ama Serwaa stocks out 1180 Yam tubers (leaves 20, reorder level is 50 -> triggers alert)
        bal_ama_yam = repo.get_or_create_balance(
            farmers[2].farmer_id,
            products["Yam Puna"].product_id,
            warehouses["Ho Cooperative Vault"].warehouse_id,
            reorder_level=50.0
        )
        service.record_movement(
            farmer_id=farmers[2].farmer_id,
            product_id=products["Yam Puna"].product_id,
            warehouse_id=warehouses["Ho Cooperative Vault"].warehouse_id,
            transaction_type="STOCK_OUT",
            quantity=1180.0,
            unit="piece",
            transaction_date=datetime.utcnow() - timedelta(days=5),
            reference_note="Bulk dispatch to Accra retail market"
        )

        print("Database seeding completed successfully!")

    except Exception as e:
        print(f"Error during seeding: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_db()
