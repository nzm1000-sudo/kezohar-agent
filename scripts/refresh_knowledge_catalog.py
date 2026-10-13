"""Refresh public titles once, without copying book bodies or asking a model."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from kezohar.knowledge_catalog import ENDPOINT,save_catalog,storage_path
from kezohar.torah_web import PublicApiTransport
from kezohar.request_budget import RequestBudget

if __name__=='__main__':
    data=PublicApiTransport(catalog_metadata=True,max_requests=1).json(ENDPOINT,request_budget=RequestBudget(seconds=40))
    print({'public_books':save_catalog(data),'catalog':str(storage_path()),'answer_evidence':False})
