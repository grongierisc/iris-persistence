Class Demo.SourceRecursiveParent Extends %Persistent
{

Property Title As %String(MAXLEN = 120) [ Required ];

Property Child As Demo.SourceRecursiveChild;

Property Address As Demo.SourceRecursiveAddress;

Storage Default
{
<Data name="SourceRecursiveParentDefaultData">
<Value name="1">
<Value>%%CLASSNAME</Value>
</Value>
<Value name="2">
<Value>Title</Value>
</Value>
<Value name="3">
<Value>Child</Value>
</Value>
<Value name="4">
<Value>Address</Value>
</Value>
</Data>
<DataLocation>^Demo.SourceRecursiveParentD</DataLocation>
<DefaultData>SourceRecursiveParentDefaultData</DefaultData>
<IdLocation>^Demo.SourceRecursiveParentD</IdLocation>
<IndexLocation>^Demo.SourceRecursiveParentI</IndexLocation>
<StreamLocation>^Demo.SourceRecursiveParentS</StreamLocation>
<Type>%Storage.Persistent</Type>
}

}
