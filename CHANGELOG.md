# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.2.0
### Added
- Consumer now updates the train stops table with live train statuses (Arrival, Departure and Pass times)
- Train statuses are parsed into `darwin.py` dataclasses

### Changed
- `db.py` inserts now commit after each batch

## 0.1.1
### Changed
- `db.py` now uses executemany instead of execute for inserts

## 0.1.0
### Added
- Initial train status populator 
- Docker compose for postgres and adminer
- Database migration script
