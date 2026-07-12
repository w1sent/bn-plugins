# API parameters: common kwargs + options dataclass, always type-hinted

API functions take common parameters (those matching BN Settings: `provider`,
`mode`) as keyword arguments with defaults from settings. Advanced/rare
parameters (temperature, custom prompt path, backoff override) go into a
typed options dataclass. All function signatures use full type hints so
IDEs and `help()` provide complete discoverability.