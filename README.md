# TrainTrack

TrainTrack is a project for live tracking of UK trains, originally implemented in a seperate project titled 'Conductor'

## Setup

1) Setup a [RailData](https://raildata.org.uk/) account
2) Subscribe to "Darwin Real Time Train Information (Push)"
3) Fetch your kafka credentials and configuration
4) Setup .env
5) Setup docker
6) Apply database migrations
7) Setup an FTP Server and configure "Darwin Timetable Files" (Raildata) to send the timetable files there

## Planned work

- [ ] Import the daily timetable and reference data.
- [ ] Add a way to query a train's latest reported location.

## Not currently planned

- Darwin supports S3 Buckets in addition to the FTP server, which can also be used to seed the timetable

## Changelog

The project changelog can be found [here](CHANGELOG.md)

## Acknowledgments

[NationalRail Data](https://www.nationalrail.co.uk/developers/) - Providing the API and data that made this project possible

## License

[MIT](LICENSE)
