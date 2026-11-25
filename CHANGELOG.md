## v0.23.0 (2026-11-26)

### Feat

- **viewer**: choose Wago or crimp on the studio price page
- **service**: read and save the splice method on the studio price page API
- **deploy**: send and pull the studio price list with server.py studio-prices

## v0.22.2 (2026-11-25)

### Fix

- **electrical**: name switch flush-box joints, drop clamp lines from the estimate

## v0.22.1 (2026-11-25)

### Fix

- **electrical**: no joints for looped sockets, only in switch flush boxes

## v0.22.0 (2026-11-25)

### Feat

- **viewer**: show back-box splices on the wiring sheet and point cards
- **electrical**: joint back-box splices with Wago clamps or crimps
- **service**: build work plan draft only from enabled services

## v0.21.0 (2026-11-25)

### Feat

- **deploy**: let server send remove a project price list
- **viewer**: show materials on the studio price page
- **core**: layer project price list over studio prices

## v0.20.1 (2026-11-25)

### Fix

- **electrical**: drop master switch point when master is answered no

## v0.20.0 (2026-11-24)

### Feat

- **viewer**: work board with tabs, cards and stage widgets
- **service**: shrink photos before storage
- **electrical**: drill partitions inside one room for cables

## v0.19.1 (2026-11-24)

### Fix

- **viewer**: keep back button on first step and put PDF button above

## v0.19.0 (2026-11-24)

### Feat

- **viewer**: print the estimate report as A4 HTML and PDF
- **viewer**: mark provisional values with a warning triangle
- **viewer**: add single-line panel diagram data to the .epd
- **electrical**: price floor heating controller and UTP cable

### Fix

- **electrical**: check breaker against assumed cable and set demand factor

## v0.18.0 (2026-11-23)

### Feat

- **admin**: icon actions and stable tables in the admin

## v0.17.0 (2026-11-23)

### Feat

- **admin**: copy issued access codes in the admin; drop env codes
- **electrical**: mark mock material totals as provisional
- **deploy**: ship backs up, rebuilds and updates the local copy

## v0.16.0 (2026-11-23)

### Feat

- **electrical**: weigh 12 V LED lines in routing and warn on long strips
- **viewer**: hide sections of services switched off for the project
- **admin**: add service checkboxes to the project card
- **service**: add per-project services switched in the admin
- **electrical**: cost ceiling passes and reuse routed holes

### Refactor

- **electrical**: split wiring and break up long elevation functions

## v0.15.1 (2026-11-22)

### Refactor

- **viewer**: drop the work-outside-estimate list from the estimate tab
- **electrical**: drop the "work outside the estimate" section

## v0.15.0 (2026-11-22)

### Feat

- **deploy**: send every model file to the server except wiring.yaml

### Fix

- **core**: skip a removed panel group in answers instead of failing the build

## v0.14.0 (2026-11-22)

### Feat

- **viewer**: grey out the floor heating sheet until its release
- **electrical**: hold floor heating back until the next release

### Fix

- **admin**: keep action buttons in one line inside table rows

## v0.13.0 (2026-11-22)

### Feat

- **viewer**: add a client tour of the project view
- **electrical**: list work outside the estimate once per table
- **viewer**: show cable length labels only for a selected line
- **electrical**: add a free site survey stage to the work plan

### Fix

- **viewer**: recalculate wiring changes with open panel questions
- **viewer**: keep a pinned hint when the sheet loses focus

## v0.12.0 (2026-11-18)

### Feat

- **viewer**: show heating, box scheme and trace in the viewer
- **pipeline**: add wiring trace and rebuild out/ for 3 projects
- **drawing**: draw heating scene and box cards in sheets
- **electrical**: add route frames, bundles and low-voltage panel zone

## v0.11.0 (2026-11-17)

### Feat

- **electrical**: route low-current cables from their source point
- **db**: keep questions and answers as revisions in tables
- **drawing**: tint the heated area warm with a red frame
- **drawing**: draw the heated area as a tint and label each zone on its sheet
- **viewer**: show work and materials apart in the tasks tab
- **viewer**: split the plumbing total into work and materials
- **viewer**: ceiling lines and floor heating table in the side panel
- **electrical,drawing**: lines on ceiling views and fixing steps 500 mm
- **drawing**: wall fill, window sills and a plan legend
- **drawing,electrical**: floor heating legend and cut-outs on the floor
- **viewer**: drop manual route editing, the build computes routes
- **drawing**: frame bundle length labels over the cables
- **electrical**: share RCDs by zone in the standard panel scheme

### Fix

- **deploy**: replace a real access code with a placeholder in .env.example
- **electrical**: wrap long floor heating misfit message
- **deploy**: send intake.yaml to the server with the model files
- **core**: keep each outer face at a collinear joint
- **drawing**: smaller sheet text sizes and anchor-touch leader rule

## v0.10.0 (2026-11-15)

### Feat

- **viewer**: hard shadows with square corners, no stepped shadow
- **drawing**: all sheets drawn at 1:25, larger scale only if plan does not fit
- **viewer**: estimate sections separated by lines
- **viewer**: project card plan draws windows as glass in the gap
- **viewer**: plan labels larger on screen, outlined, facing walls together
- **drawing**: plan labels and dimensions placed without overlaps
- **electrical**: RCD scheme, phases and floor heating protection
- **viewer**: floor heating tab and furniture layer cards
- **service**: analyze --stages for furniture and floor heating
- **electrical,model**: floor heating zones and furniture.yaml

### Fix

- **electrical**: jumper inside one wall frame runs straight along the wall
- **electrical**: standard panel puts every power group on its own RCBO

## v0.9.0 (2026-11-14)

### Feat

- **viewer**: thermostat sign, new theme and stable scrollbar gutter
- **electrical**: add thermostat point type for floor heating

### Fix

- **service**: restore lost source files on push and project import

## v0.8.0 (2026-11-13)

### Feat

- **viewer,deploy,docs**: add a What's new window from CHANGELOG.md

### Fix

- **electrical,drawing,viewer**: name section totals plainly

## v0.7.0 (2026-11-13)

### Feat

- **viewer**: draw the whole frame of points in the pinned hint
- **viewer**: draw an engineering grid under the sheets
- **viewer**: group the layers panel into sections with their own eye
- **epd**: show the whole frame of points in the pinned hint
- **electrical,drawing**: share conduits, route LED lines and one feed per group
- **model,drawing**: name walls with Latin letters in wall codes
- **viewer**: strike through declined steps in the overview list
- **viewer**: rework wizard footer, required steps and backup later
- **electrical,drawing,viewer**: draw cable turns as bend-radius arcs
- **electrical**: add comb busbars and split materials by stage
- **viewer**: add a two-level header menu by domains
- **electrical,viewer**: add LED supply box and extra work options
- **service,deploy,admin,docs**: run locally as on the server
- **viewer,agents**: add ui atoms, type scale and debug block names

### Fix

- **viewer**: keep wall pager rows square and capitalise wall names
- **viewer**: centre the zoom rail buttons again
- **viewer**: keep the accent fill on a pressed bare button
- **electrical**: use 4x1.5 between pass switches without a box

## v0.6.0 (2026-11-12)

### Feat

- **electrical,drawing,viewer**: route drops beside openings, drop conduit entries
- **service,db,viewer,admin**: add product feedback from the viewer

## v0.5.1 (2026-11-12)

### Feat

- **electrical,drawing,viewer**: mark material prices as a placeholder

### Fix

- **drawing**: draw panel sheet rails as in the chosen enclosure

## v0.5.0 (2026-11-12)

### Feat

- **service,db,viewer**: add the Tasks tab, acceptance ticks and acting for the client
- **electrical,drawing,viewer**: show room ceilings on elevations, drop mounting sheet
- **electrical,viewer**: assume group cables on the panel, stack switches
- **service,db**: add installation by tasks with plans, photos and payments
- **electrical,plumbing**: draft installation tasks from the estimates
- **viewer**: layer electrical views by system, light links in 3D, socket stacks
- **electrical,drawing**: add mounting sheet, light chains, LED supply and wall names
- **service**: ask for a PDF instead of reading DWG and DXF sources
- **viewer**: overview progress, zone floors, backup peak, splash and wall grid
- **core,service,db**: client questions with studio review, client access code
- **core**: room zones as plan floors, low-voltage cabinet, wiring neighbours
- **electrical**: size the backup bus by design peak, not installed sum
- **drawing**: draw switch-to-light links at right angles

### Fix

- **viewer**: accept the shown group set on Next in the wizard
- **electrical**: narrow chase holds only one conduit

## v0.4.3 (2026-11-10)

### Fix

- **deploy**: bump @types/node so npm ci resolves vite 8 peers

## v0.4.2 (2026-11-10)

### Feat

- **electrical,viewer**: add the work scope next to the estimate
- **electrical,viewer**: add three-phase panel and master switch
- **viewer**: move variant choice into the setup wizard
- **viewer**: add system views, click selection and reserve page
- **electrical,service**: add wiring options and the wizard API
- **cli**: split cli.py into a package, guard serve with login
- **service**: check access in the service API, add a task queue
- **electrical,viewer**: add panel device stickers and a PDF to print
- **service**: keep only the last builds of a project in storage

### Fix

- **deploy**: send server.py scripts as one argument, not through stdin
- **service,deploy**: answer 404 for lost build files, warn without volume

### Refactor

- **service**: drop the POST /variant endpoint in favour of /wizard
- **viewer**: split PanelView into painter and parts
- **drawing**: split plumbing.py into pipe_paths and plumbing_legend

## v0.4.1 (2026-11-04)

### Feat

- **deploy**: add flow.py ship, release --increment and scripts/server.py
- **drawing,viewer**: add cable layers by purpose, protection and route
- **viewer**: show a question's object on the drawing

### Fix

- **deploy**: make cz bump tags annotated so --follow-tags pushes them
- **viewer**: show the legend title in the project language
- **electrical**: ask panel questions in the project language

### Refactor

- **service**: split long API route functions by topic
- **plumbing**: split network.py into focused modules
- **core**: split pipeline.py into the pipeline package

## v0.4.0 (2026-11-04)

### Feat

- **service**: fill blank projects on import, add project build
- **viewer**: answer questions right in the question card
- **core,service**: save viewer answers to answers.yaml

## v0.3.0 (2026-11-03)

### Feat

- **deploy,service**: deploy on the database with a one-time seed import
- **viewer**: link admin project page to the viewer by id
- **service,db**: make project slug unique per studio
- **viewer,service**: key viewer projects by id instead of name
- **service,db**: serve the viewer API from the database
- **service,db**: sync a project folder with the database
- **service,db**: build a project from the database into object storage
- **service,db**: keep all model files and add object storage by key
- **admin,deploy**: add the platform admin front at /admin/
- **service,db**: return state words and event names from the admin API
- **service,db**: add platform admin API for the superuser
- **service,db**: keep each studio's projects and prices in its own folder
- **service,db**: enforce one workspace per person and query visible projects
- **viewer**: move studio price list into studio settings

### Fix

- **deploy**: exit non-zero when view or Caddy stops
- **core**: reject non-dict wiring edits with a field error
- **deploy**: keep server studio prices and profile on redeploy

## v0.2.0 (2026-11-03)

### Feat

- **electrical,viewer**: add market spread of work prices
- **electrical,plumbing,viewer**: split estimate works into rough and finish
- **electrical,viewer**: limit wiring variants to project routes
- **drawing**: draw switch-to-light links as straight segments
- **viewer**: zoom in one step on double click, fit at the last step
- **viewer,service**: show app version and alpha stage, brand as Shtroba
