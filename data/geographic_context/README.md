# Geographic context

Reserved for territorial data: the Car Independence Index (CII) per municipality / zone, PT
quality class and sharing availability class.

Empty on purpose: the CII dataset will be provided later. Until then the model only uses the
coarse `Location.area_type` (city centre / urban / suburban / peripheral) and the optional
`car_independence_index`, `pt_quality`, `sharing_availability` fields of a profile.

When the data arrives, add the file here and a loader next to `app/data/loader.py`. The CII is a
contextual prior, never a deterministic rule (CLAUDE.md section 18).
