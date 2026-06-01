package tier

// WithFallback runs op; if it returns an error AsLimitError recognizes,
// invokes onLimit with the parsed *LimitError and returns nil. Otherwise
// the error propagates unchanged.
//
// Use this around best-effort calls (eventing, optional sinks) where tier
// denials shouldn't break the broader operation:
//
//	err := tier.WithFallback(
//	    func() error {
//	        _, err := pubsubClient.Publish(ctx, &pubsub.Message{Data: payload}).Get(ctx)
//	        return err
//	    },
//	    func(tle *tier.LimitError) {
//	        log.Printf("Pub/Sub denied (upgrade_to=%s): %s", tle.UpgradeTo, tle.Reason)
//	    },
//	)
//	// err == nil even if the publish was tier-denied; non-tier errors still surface
func WithFallback(op func() error, onLimit func(*LimitError)) error {
	err := op()
	if err == nil {
		return nil
	}
	if tle, ok := AsLimitError(err); ok {
		if onLimit != nil {
			onLimit(tle)
		}
		return nil
	}
	return err
}

// WithFallbackResult is the value-returning variant. If op returns a
// tier-limit error, returns (zero value, nil) after running onLimit.
//
//	val, err := tier.WithFallbackResult(
//	    func() (string, error) { return s3Client.GetObject(...) },
//	    func(tle *tier.LimitError) { log.Print(tle.Reason) },
//	)
func WithFallbackResult[T any](op func() (T, error), onLimit func(*LimitError)) (T, error) {
	val, err := op()
	if err == nil {
		return val, nil
	}
	if tle, ok := AsLimitError(err); ok {
		if onLimit != nil {
			onLimit(tle)
		}
		var zero T
		return zero, nil
	}
	return val, err
}
