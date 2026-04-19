Class Demo.SourceRecursiveAddress Extends %SerialObject
{

Property Street As %String(MAXLEN = 120) [ Required ];

Property ZipCode As %String(MAXLEN = 12);

Property Country As %String(MAXLEN = 2) [ InitialExpression = "FR" ];

Storage Default
{
<Data name="SourceRecursiveAddressState">
<Value name="1">
<Value>Street</Value>
</Value>
<Value name="2">
<Value>ZipCode</Value>
</Value>
<Value name="3">
<Value>Country</Value>
</Value>
</Data>
<State>SourceRecursiveAddressState</State>
<StreamLocation>^Demo.SourceRecursiveAddressS</StreamLocation>
<Type>%Storage.Serial</Type>
}

}
