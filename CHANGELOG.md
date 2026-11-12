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
