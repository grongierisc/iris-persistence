Class Demo.SourceRequestFixture Extends Ens.Request
{

Property CorrelationId As %String(MAXLEN = 64) [ Required ];

Property RetryCount As %Integer [ InitialExpression = 0 ];

Property SourceSystem As %String(MAXLEN = 32) [ InitialExpression = "ERP" ];

Storage Default
{
<Data name="SourceRequestFixtureDefaultData">
<Subscript>"SourceRequestFixture"</Subscript>
<Value name="1">
<Value>CorrelationId</Value>
</Value>
<Value name="2">
<Value>RetryCount</Value>
</Value>
<Value name="3">
<Value>SourceSystem</Value>
</Value>
</Data>
<DefaultData>SourceRequestFixtureDefaultData</DefaultData>
<Type>%Storage.Persistent</Type>
}

}
