# 运行测试与演示

```bash
python -m unittest discover -s tests -v
uvicorn app.main:app --reload --port 8000
```

预期 3 个测试通过。